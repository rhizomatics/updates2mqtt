from __future__ import annotations

import re
import typing
from abc import abstractmethod
from pathlib import Path
from typing import Any, cast

import structlog
from docker.auth import resolve_repository_name
from docker.models.containers import Container
from hishel import CacheOptions, SpecificationPolicy  # pyright: ignore[reportAttributeAccessIssue]
from hishel.httpx import SyncCacheClient
from omegaconf import MissingMandatoryValue, OmegaConf, ValidationError

from updates2mqtt.helpers import (
    APIStatsCounter,
    CacheMetadata,
    Throttler,
    fetch_url,
    validate_url,
)
from updates2mqtt.model import DiscoveryArtefactDetail, DiscoveryInstallationDetail, ReleaseDetail
from updates2mqtt.oci import (
    AuthenticationError,
    Blob,
    CredentialStore,
    Descriptor,
    DockerConfigCredentials,
    HttpRequest,
    HttpResponse,
    InvalidReferenceError,
    Manifest,
    OCIError,
    Platform,
    RateLimitedError,
    Reference,
    RegistryClient,
    ResolvedImage,
    Transport,
    TransportError,
)
from updates2mqtt.oci.transports.httpx_transport import HttpxTransport

if typing.TYPE_CHECKING:
    from docker.models.images import RegistryData
    from httpx import Response
    from omegaconf.dictconfig import DictConfig
from http import HTTPStatus

import docker
import docker.errors

from updates2mqtt.config import (
    PKG_INFO_FILE,
    SOURCE_PLATFORM_GITHUB,
    SOURCE_PLATFORM_GITLAB,
    SOURCE_PLATFORMS,
    CommonPackages,
    DockerConfig,
    DockerPackageUpdateInfo,
    MetadataSourceConfig,
    PackageUpdateInfo,
    RegistryConfig,
    StrKeyedDict,
    VersionPolicy,
    docker_image_names,
)

log: Any = structlog.get_logger()

DIFF_URL_TEMPLATES = {
    SOURCE_PLATFORM_GITHUB: "{repo}/commit/{revision}",
}
RELEASE_URL_TEMPLATES = {
    SOURCE_PLATFORM_GITHUB: "{repo}/releases/tag/{version}",
}
UNKNOWN_RELEASE_URL_TEMPLATES = {
    SOURCE_PLATFORM_GITHUB: "{repo}/releases",
    SOURCE_PLATFORM_GITLAB: "{repo}/container_registry",
}
MISSING_VAL = "**MISSING**"
UNKNOWN_REGISTRY = "**UNKNOWN_REGISTRY**"
UNKNOWN_NAME = "**UNKNOWN_NAME**"
# Portainer stacks run compose from /data/compose/<stack id> inside the Portainer container
PORTAINER_COMPOSE_PATH = re.compile(r"^/data/compose/(\d+)(?:/|$)")

REGISTRY_GHCR = "ghcr.io"
REGISTRY_DOCKER = "docker.io"
REGISTRY_MCR = "mcr.microsoft.com"
REGISTRY_QUAY = "quay.io"
REGISTRY_LSCR = "lscr.io"
REGISTRY_CODEBERG = "codeberg.org"
REGISTRY_GITLAB = "registry.gitlab.com"
REGISTRY_BITBUCKET = "crg.apkg.io"

# where a registry implies the source repository, by image name
REPO_TEMPLATES: dict[str, str] = {
    REGISTRY_GHCR: "https://github.com/{image_name}",
    REGISTRY_CODEBERG: "https://codeberg.org/{image_name}",
    REGISTRY_GITLAB: "https://gitlab.com/{image_name}",
}
# timeout for each registry request
REGISTRY_TIMEOUT = 30.0

# source: https://specs.opencontainers.org/distribution-spec/?v=v1.0.0#pull
OCI_NAME_RE = r"[a-z0-9]+((\.|_|__|-+)[a-z0-9]+)*(\/[a-z0-9]+((\.|_|__|-+)[a-z0-9]+)*)*"
OCI_TAG_RE = r"[a-zA-Z0-9_][a-zA-Z0-9._-]{0,127}"


class DockerImageInfo(DiscoveryArtefactDetail):
    """Normalize and shlep around the bits of an image def

    index_name: aka index_name, e.g. ghcr.io
    name: image ref without index name or tag, e.g. nginx, or librenms/librenms
    tag: tag or digest
    untagged_ref:  combined index name and package name
    """

    def __init__(
        self,
        ref: str,  # ref with optional index name and tag or digest, index:name:tag_or_digest
        image_digest: str | None = None,
        tags: list[str] | None = None,
        attributes: dict[str, Any] | None = None,
        annotations: dict[str, Any] | None = None,
        platform: str | None = None,  # test harness simplification
        version: str | None = None,  # test harness simplification
        created: str | None = None,
    ) -> None:
        super().__init__()
        self.ref: str = ref
        self.version: str | None = version
        self.image_digest: str | None = image_digest
        self.short_digest: str | None = None
        self.repo_digest: str | None = None  # the single RepoDigest known to match registry
        self.git_digest: str | None = None
        self.index_name: str | None = None
        self.name: str | None = None
        self.tag: str | None = None
        self.pinned_digest: str | None = None
        # untagged ref using combined index and remote name used only for pattern matching common pkg info
        self.untagged_ref: str | None = None  # index_name/remote_name used for pkg match
        self.tag_or_digest: str | None = None  # index_name/remote_name:**tag_or_digest**
        self.tags = tags
        self.attributes: dict[str, Any] = attributes or {}
        self.annotations: dict[str, Any] = annotations or {}
        self.throttled: bool = False
        self.origin: str | None = None
        self.error: str | None = None
        self.platform: str | None = platform
        self.custom: dict[str, str | float | int | bool | None] = {}
        self.created: str | None = created

        self.local_build: bool = not self.repo_digests
        self.index_name, remote_name = resolve_repository_name(ref)

        self.name = remote_name

        if remote_name and ":" in remote_name and ("@" not in remote_name or remote_name.index("@") > remote_name.index(":")):
            # name:tag format
            self.name, self.tag_or_digest = remote_name.split(":", 1)
            self.untagged_ref = ref.split(":", 1)[0]
            self.tag = self.tag_or_digest

        elif remote_name and "@" in remote_name:
            # name@digest format
            self.name, self.tag_or_digest = remote_name.split("@", 1)
            self.untagged_ref = ref.split("@", 1)[0]
            self.pinned_digest = self.tag_or_digest

        if self.tag and "@" in self.tag:
            # name:tag@digest format
            # for pinned tags, care only about the digest part
            self.tag, self.tag_or_digest = self.tag.split("@", 1)
            self.pinned_digest = self.tag_or_digest
        if self.tag_or_digest is None:
            self.tag_or_digest = "latest"
            self.untagged_ref = ref
            self.tag = self.tag_or_digest

        if self.repo_digest is None and len(self.repo_digests) == 1:
            # definite known RepoDigest
            # if its ambiguous, the final version selection will handle it
            self.repo_digest = self.repo_digests[0]

        if self.index_name == "docker.io" and "/" not in self.name:
            # "official Docker images have an abbreviated library/foo name"
            self.name = f"library/{self.name}"
        if self.name is not None and not re.match(OCI_NAME_RE, self.name):
            log.warning("Invalid OCI image name: %s", self.name)
        if self.tag and not re.match(OCI_TAG_RE, self.tag):
            log.warning("Invalid OCI image tag: %s", self.tag)
        if "/" in self.name:
            self.unqualified_name: str = self.name.split("/", 1)[1]
        else:
            self.unqualified_name = self.name

        if self.os and self.arch:
            self.platform = "/".join(
                filter(
                    None,
                    [self.os, self.arch, self.variant],
                ),
            )

        if self.image_digest is not None:
            self.image_digest = self.condense_digest(self.image_digest, short=False)
            self.short_digest = self.condense_digest(self.image_digest)

    @property
    def repo_digests(self) -> list[str]:
        if self.repo_digest:
            return [self.repo_digest]
        # RepoDigest in image inspect, Registry Config object
        digests = [v.split("@", 1)[1] if "@" in v else v for v in self.attributes.get("RepoDigests", [])]
        return digests or []

    @property
    def pinned(self) -> bool:
        """Check if this is pinned and installed version consistent with pin"""
        return bool(self.pinned_digest and self.pinned_digest in self.repo_digests)

    @property
    def os(self) -> str | None:
        return self.attributes.get("Os")

    @property
    def arch(self) -> str | None:
        return self.attributes.get("Architecture")

    @property
    def variant(self) -> str | None:
        return self.attributes.get("Variant")

    def condense_digest(self, digest: str | None, short: bool = True) -> str | None:
        if digest is None:
            return None
        try:
            digest = digest.split("@")[1] if "@" in digest else digest  # fully qualified RepoDigest
            if short:
                digest = digest.split(":")[1] if ":" in digest else digest  # remove digest type prefix
                return digest[0:12]
            return digest
        except Exception as e:
            log.warning("Unable to condense digest %s: %s", digest, e)
            return None

    def reuse(self) -> DockerImageInfo:
        cloned = DockerImageInfo(
            self.ref, self.image_digest, self.tags, self.attributes, self.annotations, self.version, self.created
        )
        cloned.origin = "REUSED"
        return cloned

    def as_dict(self, minimal: bool = True) -> StrKeyedDict:
        result: StrKeyedDict = {
            "captured": self.captured.isoformat(),
            "image_ref": self.ref,
            "name": self.name,
            "version": self.version,
            "image_digest": self.image_digest,
            "repo_digest": self.repo_digest,
            "repo_digests": self.repo_digest,
            "git_digest": self.git_digest,
            "index_name": self.index_name,
            "tag": self.tag,
            "pinned_digest": self.pinned_digest,
            "tag_or_digest": self.tag_or_digest,
            "tags": self.tags,
            "origin": self.origin,
            "platform": self.platform,
            "local_build": self.local_build,
            "error": self.error,
            "throttled": self.throttled,
            "custom": self.custom,
        }
        if not minimal:
            result["attributes"] = self.attributes
            result["annotations"] = self.annotations
        return result


def id_source_platform(source: str | None) -> str | None:
    candidates: list[str] = [platform for platform, pattern in SOURCE_PLATFORMS.items() if re.match(pattern, source or "")]
    return candidates[0] if candidates else None


def _select_annotation(
    name: str, key: str, local_info: DockerImageInfo | None = None, registry_info: DockerImageInfo | None = None
) -> dict[str, str | None]:
    result: dict[str, str | None] = {}
    if registry_info:
        v: Any | None = registry_info.annotations.get(key)
        if v is not None:
            result[name] = v
    elif local_info:
        v = local_info.annotations.get(key)
        if v is not None:
            result[name] = v
    return result


def cherrypick_annotations(
    local_info: DockerImageInfo, registry_info: DockerImageInfo | None
) -> dict[str, str | float | int | bool | None]:
    """https://github.com/opencontainers/image-spec/blob/main/annotations.md"""
    results: dict[str, str | float | int | bool | None] = {}
    for either_name, either_label in [
        ("documentation_url", "org.opencontainers.image.documentation"),
        ("description", "org.opencontainers.image.description"),
        ("licences", "org.opencontainers.image.licenses"),
        ("image_base", "org.opencontainers.image.base.name"),
        ("image_created", "org.opencontainers.image.created"),
        ("image_version", "org.opencontainers.image.version"),
        ("image_revision", "org.opencontainers.image.revision"),
        ("ref_name", "org.opencontainers.image.ref.name"),
        ("title", "org.opencontainers.image.title"),
        ("vendor", "org.opencontainers.image.vendor"),
        ("source", "org.opencontainers.image.source"),
    ]:
        results.update(_select_annotation(either_name, either_label, local_info, registry_info))
    if (
        results.get("ref_name") == "ubuntu"
        and local_info.name != "ubuntu"
        and results.get("image_version")
        and re.fullmatch(r"^2\d\.\d\d$", str(results["image_version"]))
    ):
        log.debug(
            "Suppressing %s base %s version leaking into image version: %s",
            local_info.name,
            results["ref_name"],
            results["image_version"],
        )
        del results["image_version"]
    return results


class DockerServiceDetails(DiscoveryInstallationDetail):
    def __init__(
        self,
        container_name: str | None = None,
        compose_path: str | None = None,
        compose_version: str | None = None,
        compose_service: str | None = None,
        git_repo_path: str | None = None,
        compose_project: str | None = None,
    ) -> None:
        self.container_name: str | None = container_name
        self.compose_path: str | None = compose_path
        self.compose_version: str | None = compose_version
        self.compose_service: str | None = compose_service
        self.compose_project: str | None = compose_project
        self.git_repo_path: str | None = git_repo_path
        self.git_local_timestamp: str | None = None

    @property
    def compose_path_found(self) -> bool:
        """Compose working dir label is visible inside this container, so compose can be run there"""
        return self.compose_path is not None and Path(self.compose_path).is_dir()

    @property
    def portainer_stack_id(self) -> str | None:
        """Portainer stacks have a working dir inside Portainer's own data volume"""
        if self.compose_path:
            match = PORTAINER_COMPOSE_PATH.match(self.compose_path)
            if match:
                return match.group(1)
        return None

    def as_dict(self) -> StrKeyedDict:
        results: StrKeyedDict = {
            "container_name": self.container_name,
            "compose_path": self.compose_path,
            "compose_path_found": self.compose_path_found,
            "compose_project": self.compose_project,
            "compose_service": self.compose_service,
            "compose_version": self.compose_version,
        }
        if self.portainer_stack_id:
            results["portainer_stack_id"] = self.portainer_stack_id
        if self.git_local_timestamp:
            results["git_local_timestamp"] = self.git_local_timestamp
        if self.git_repo_path:
            results["git_repo_path"] = self.git_repo_path
        return results


class LocalContainerInfo:
    def build_image_info(self, container: Container) -> tuple[DockerImageInfo, DockerServiceDetails]:
        """Image contents equiv to `docker inspect image <image_ref>`"""
        # container image can be none if someone ran `docker rmi -f`
        # so although this could be sourced from image, like `container.image.tags[0]`
        # use the container ref instead, which survives monkeying about with images
        image_ref: str = ""
        image_digest: str | None = None
        if container.attrs:
            image_ref = container.attrs.get("Config", {}).get("Image") or ""
            image_digest = container.attrs.get("Image")

        image_info: DockerImageInfo = DockerImageInfo(
            image_ref,
            image_digest=image_digest,
            tags=container.image.tags if container and container.image else None,
            annotations=container.image.labels if container.image else None,
            attributes=container.image.attrs if container.image else None,
        )
        service_info: DockerServiceDetails = DockerServiceDetails(
            container.name,
            compose_path=container.labels.get("com.docker.compose.project.working_dir"),
            compose_service=container.labels.get("com.docker.compose.service"),
            compose_version=container.labels.get("com.docker.compose.version"),
            compose_project=container.labels.get("com.docker.compose.project"),
        )

        labels: dict[str, str | float | int | bool | None] = cherrypick_annotations(image_info, None)
        # capture container labels/annotations, not image ones
        labels = labels or {}
        if container.image and container.image.attrs:
            image_info.created = container.image.attrs.get("Created")
        image_info.custom = labels
        image_info.version = cast("str|None", labels.get("image_version"))

        return image_info, service_info


class PackageEnricher:
    def __init__(self, docker_cfg: DockerConfig, packages: dict[str, PackageUpdateInfo] | None = None) -> None:
        self.pkgs: dict[str, PackageUpdateInfo] = packages or {}
        self.cfg: DockerConfig = docker_cfg
        self.log: Any = structlog.get_logger().bind(integration="docker")

    def initialize(self) -> None:
        pass

    def enrich(self, image_info: DockerImageInfo) -> PackageUpdateInfo | None:
        def match(pkg: PackageUpdateInfo) -> bool:
            if pkg is not None and pkg.docker is not None and pkg.docker.image_name is not None:
                image_names = docker_image_names(pkg.docker)
                if image_info.untagged_ref is not None and image_info.untagged_ref in image_names:
                    return True
                if image_info.ref is not None and image_info.ref in image_names:
                    return True
            return False

        if image_info.untagged_ref is not None and image_info.ref is not None:
            for pkg in self.pkgs.values():
                if match(pkg) and pkg.docker:
                    self.log.debug(
                        "Found common package",
                        image_name=pkg.docker.image_name,
                        logo_url=pkg.logo_url,
                        relnotes_url=pkg.release_notes_url,
                    )
                    return pkg
        return None


class DefaultPackageEnricher(PackageEnricher):
    def enrich(self, image_info: DockerImageInfo) -> PackageUpdateInfo | None:
        self.log.debug("Default pkg info", image_name=image_info.untagged_ref, image_ref=image_info.ref)
        return PackageUpdateInfo(
            DockerPackageUpdateInfo(image_info.untagged_ref or image_info.ref, version_policy=VersionPolicy.AUTO),
            logo_url=self.cfg.default_entity_picture_url,
            release_notes_url=None,
        )


class CommonPackageEnricher(PackageEnricher):
    def initialize(self) -> None:
        base_cfg: DictConfig = OmegaConf.structured(CommonPackages)
        if PKG_INFO_FILE.exists():
            self.log.debug("Loading common package update info", path=PKG_INFO_FILE)
            cfg: DictConfig = typing.cast("DictConfig", OmegaConf.merge(base_cfg, OmegaConf.load(PKG_INFO_FILE)))

            OmegaConf.to_container(cfg, throw_on_missing=True)
            OmegaConf.set_readonly(cfg, True)
        else:
            self.log.warning("No common package update info found", path=PKG_INFO_FILE)
            cfg = base_cfg
        try:
            common_config: CommonPackages = typing.cast("CommonPackages", cfg)
            # omegaconf broken-ness on optional fields and converting to backclasses
            self.pkgs = common_config.common_packages
            # self.pkgs: dict[str, PackageUpdateInfo] = {
            #    pkg: PackageUpdateInfo(**pkg_cfg) for pkg, pkg_cfg in cfg.common_packages.items() if pkg not in self.pkgs
            # }
        except (MissingMandatoryValue, ValidationError) as e:
            self.log.serror("Configuration error %s", e, path=PKG_INFO_FILE.as_posix())
            raise


class LinuxServerIOPackageEnricher(PackageEnricher):
    def initialize(self) -> None:
        cfg: MetadataSourceConfig | None = self.cfg.discover_metadata.get("linuxserver.io")
        if cfg is None or not cfg.enabled:
            return

        self.log.debug(f"Fetching linuxserver.io metadata from API, cache_ttl={cfg.cache_ttl}")
        response: Response | None = fetch_url(
            "https://api.linuxserver.io/api/v1/images?include_config=false&include_deprecated=false",
            cache_ttl=cfg.cache_ttl,
        )
        if response and response.is_success:
            api_data: Any = response.json()
            repos: list[dict[str, Any]] = api_data.get("data", {}).get("repositories", {}).get("linuxserver", [])
        else:
            return

        added = 0
        for repo in repos:
            image_name = repo.get("name")
            if image_name and image_name not in self.pkgs:
                github_url: str | None = repo.get("github_url")
                self.pkgs[image_name] = PackageUpdateInfo(
                    DockerPackageUpdateInfo(f"lscr.io/linuxserver/{image_name}"),
                    logo_url=repo.get("project_logo"),
                    release_notes_url=f"{github_url}/releases" if github_url else None,
                )
                added += 1
        self.log.debug(f"Added {added} linuxserver.io package details")


class SourceReleaseEnricher:
    def __init__(self) -> None:
        self.log: Any = structlog.get_logger().bind(integration="docker")

    def enrich(
        self, registry_info: DockerImageInfo, source_repo_url: str | None = None, notes_url: str | None = None
    ) -> ReleaseDetail | None:
        detail = ReleaseDetail(registry_info.name or UNKNOWN_NAME)

        detail.notes_url = notes_url
        detail.version = registry_info.annotations.get("org.opencontainers.image.version")
        detail.revision = registry_info.annotations.get("org.opencontainers.image.revision")
        # explicit source_repo_url overrides container, e.g. where container source is only the docker wrapper
        detail.source_url = source_repo_url or registry_info.annotations.get("org.opencontainers.image.source")

        if detail.source_url is None and registry_info is not None and registry_info.index_name is not None:
            repo_template: str | None = REPO_TEMPLATES.get(registry_info.index_name)
            if repo_template:
                source_url = repo_template.format(image_name=registry_info.name)
                if validate_url(source_url, cache_ttl=86400):
                    detail.source_url = source_url
                    self.log.info("Implied source from registry: %s", detail.source_url)

        if detail.source_url is None and detail.notes_url is None and detail.revision is None and detail.version is None:
            return None

        if detail.source_url and "#" in detail.source_url:
            detail.source_repo_url = detail.source_url.split("#", 1)[0]
            self.log.debug("Simplifying %s from %s", detail.source_repo_url, detail.source_url)
        else:
            detail.source_repo_url = detail.source_url

        detail.source_platform = id_source_platform(detail.source_repo_url)
        if not detail.source_platform:
            self.log.debug("No known source platform found on container", source=detail.source_repo_url)
            return detail

        template_vars: dict[str, str | None] = {
            "version": detail.version or MISSING_VAL,
            "revision": detail.revision or MISSING_VAL,
            "repo": detail.source_repo_url or MISSING_VAL,
            "source": detail.source_url or MISSING_VAL,
        }

        try:
            diff_url_template: str | None = DIFF_URL_TEMPLATES.get(detail.source_platform)
            diff_url: str | None = diff_url_template.format(**template_vars) if diff_url_template else None
            if diff_url and MISSING_VAL not in diff_url and validate_url(diff_url, cache_ttl=3600):
                detail.diff_url = diff_url
            else:
                diff_url = None

            if detail.notes_url is None and detail.source_platform in RELEASE_URL_TEMPLATES:
                platform_notes_url: str | None = RELEASE_URL_TEMPLATES[detail.source_platform].format(**template_vars)
                if (
                    platform_notes_url
                    and MISSING_VAL not in platform_notes_url
                    and validate_url(platform_notes_url, cache_ttl=86400)
                ):
                    self.log.debug("Setting default known release notes url: %s", platform_notes_url)
                    detail.notes_url = platform_notes_url

            if detail.notes_url is None and detail.source_platform in UNKNOWN_RELEASE_URL_TEMPLATES:
                platform_notes_url = UNKNOWN_RELEASE_URL_TEMPLATES[detail.source_platform].format(**template_vars)
                if (
                    platform_notes_url
                    and MISSING_VAL not in platform_notes_url
                    and validate_url(platform_notes_url, cache_ttl=86400)
                ):
                    self.log.debug("Setting default unknown release notes url: %s", platform_notes_url)
                    detail.notes_url = platform_notes_url
        except Exception as e:
            self.log.error("Failed formatting enriched URLs with %s: %s", template_vars, e)

        return detail


class VersionLookup:
    def __init__(self) -> None:
        self.log: Any = structlog.get_logger().bind(integration="docker", tool="version_lookup")

    @abstractmethod
    def lookup(self, local_image_info: DockerImageInfo, **kwargs: Any) -> DockerImageInfo:
        pass


def registry_cache_ttl(cfg: RegistryConfig, request: HttpRequest) -> int | None:
    """Tokens and tag lookups expire, content addressed by digest can be kept"""
    if request.kind == "token":
        return cfg.token_cache_ttl
    if request.immutable:
        return cfg.immutable_cache_ttl
    return cfg.mutable_cache_ttl


class CachingRegistryTransport(HttpxTransport):
    """hishel cached httpx, with cache lifetimes by kind of registry request, and API stats"""

    def __init__(self, cfg: RegistryConfig, api_stats: APIStatsCounter | None = None) -> None:
        self.cfg: RegistryConfig = cfg
        self.api_stats: APIStatsCounter | None = api_stats
        client = SyncCacheClient(
            timeout=REGISTRY_TIMEOUT,
            policy=SpecificationPolicy(cache_options=CacheOptions(shared=False, allow_stale=False)),
        )
        super().__init__(client, prepare=self.set_cache_ttl)
        self.owns_client = True

    def set_cache_ttl(self, request: HttpRequest, kwargs: dict[str, Any]) -> None:
        ttl: int | None = registry_cache_ttl(self.cfg, request)
        if ttl is not None:
            kwargs["headers"]["Cache-Control"] = f"max-age={ttl}"
            kwargs["extensions"]["hishel_ttl"] = ttl

    def send(self, request: HttpRequest) -> HttpResponse:
        try:
            response: HttpResponse = super().send(request)
        except TransportError:
            if self.api_stats:
                self.api_stats.stats(request.url, None)
            raise
        if self.api_stats:
            self.api_stats.stats(request.url, response.native)
        return response


def cache_metadata(response: HttpResponse | None) -> CacheMetadata | None:
    """hishel's cache details, where the transport is httpx"""
    native: Any = response.native if response else None
    return CacheMetadata(native) if native is not None and hasattr(native, "extensions") else None


class ContainerDistributionAPIVersionLookup(VersionLookup):
    """Latest image details from the registry, via the OCI distribution API

    Credentials come from the Docker config, e.g. `~/.docker/config.json`, as saved by `docker login`
    """

    def __init__(
        self,
        throttler: Throttler,
        cfg: RegistryConfig,
        credentials: CredentialStore | None = None,
        transport: Transport | None = None,
    ) -> None:
        self.throttler: Throttler = throttler
        self.cfg: RegistryConfig = cfg
        self.log: Any = structlog.get_logger().bind(integration="docker", tool="version_lookup")
        self.api_stats = APIStatsCounter()
        self.client: RegistryClient = RegistryClient(
            transport or CachingRegistryTransport(cfg, self.api_stats),
            credentials=credentials if credentials is not None else DockerConfigCredentials(),
        )

    def lookup(
        self,
        local_image_info: DockerImageInfo,
        token: str | None = None,
        minimal: bool = False,
        **kwargs: Any,
    ) -> DockerImageInfo:
        result: DockerImageInfo = DockerImageInfo(local_image_info.ref)
        index_name: str | None = local_image_info.index_name
        if not local_image_info.name or not index_name:
            self.log.debug("No local pkg name or registry index name to check")
            return result

        if self.throttler.check_throttle(index_name):
            result.throttled = True
            return result

        try:
            # by tag where there is one, to find what it points to now, even if pinned to a digest
            ref = Reference(
                registry=index_name,
                repository=local_image_info.name,
                tag=local_image_info.tag,
                digest=None if local_image_info.tag else local_image_info.pinned_digest,
            )
        except InvalidReferenceError as e:
            self.log.warning("Unable to look up %s in registry: %s", local_image_info.ref, e)
            result.error = str(e)
            return result
        platform: Platform | None = (
            Platform(local_image_info.os, local_image_info.arch, local_image_info.variant)
            if local_image_info.os and local_image_info.arch
            else None
        )

        try:
            image: ResolvedImage = self.client.resolve(ref, platform, fetch_config=False, token=token)
        except RateLimitedError as e:
            self.throttle(index_name, e)
            result.throttled = True
            return result
        except AuthenticationError as e:
            self.log.warning("Authentication error prevented Docker Registry enrichment: %s", e)
            result.error = str(e)
            return result
        except OCIError as e:
            self.log.warning("Failed to fetch %s from registry: %s", local_image_info.ref, e)
            result.error = str(e)
            return result

        top: Manifest | None = image.top
        result.annotations = dict(top.annotations) if top else {}
        index_cache_metadata: CacheMetadata | None = cache_metadata(top.response if top else None)
        manifest_cache_metadata: CacheMetadata | None = None
        config_cache_metadata: CacheMetadata | None = None

        if image.manifest is not None:
            result.image_digest = image.digest
            result.short_digest = result.condense_digest(image.digest)
            self.log.debug("Setting %s image digest %s", result.name, result.short_digest)
            if image.index is not None:
                manifest_cache_metadata = cache_metadata(image.manifest.response)
            config_cache_metadata = self.apply_manifest(result, image, local_image_info, token, minimal)
        elif platform:
            self.log.debug("No %s platform image in registry index for %s", platform, local_image_info.ref)

        if not result.annotations:
            self.log.debug("No annotations found from registry data")

        labels: dict[str, str | float | int | bool | None] = cherrypick_annotations(local_image_info, result)
        result.custom = labels or {}
        if index_cache_metadata:
            result.custom["index_cache_age"] = index_cache_metadata.age
        if manifest_cache_metadata:
            result.custom["manifest_cache_age"] = manifest_cache_metadata.age
        if config_cache_metadata:
            result.custom["config_cache_age"] = config_cache_metadata.age
        result.version = cast("str|None", labels.get("image_version"))
        result.origin = "OCI_V2" if not minimal else "OCI_V2_MINIMAL"

        self.log.debug(
            "OCI_V2 Lookup for %s: short_digest:%s, repo_digest:%s, version: %s",
            local_image_info.name,
            result.short_digest,
            result.repo_digest,
            result.version,
        )
        return result

    def throttle(self, index_name: str, error: RateLimitedError) -> None:
        retry_secs: int | None = round(error.retry_after) if error.retry_after else None
        self.throttler.throttle(index_name, retry_secs=retry_secs, explanation=str(error))

    def apply_manifest(
        self,
        result: DockerImageInfo,
        image: ResolvedImage,
        local_image_info: DockerImageInfo,
        token: str | None,
        minimal: bool,
    ) -> CacheMetadata | None:
        """Repo digest and annotations from the platform manifest, and labels from its config"""
        if image.manifest is None:
            return None
        config: Descriptor | None = image.manifest.config
        if config is None:
            self.log.warning("Empty config digest for %s", local_image_info.ref)
        else:
            result.repo_digest = result.condense_digest(config.digest, short=False)
            self.log.debug("Setting %s repo digest: %s", result.name, result.repo_digest)
        result.annotations.update(image.manifest.annotations)
        if minimal or config is None:
            return None

        try:
            blob: Blob = self.client.get_blob(image.reference, config.digest, media_type=config.media_type, token=token)
            image.config = blob.json()
            image.config_blob = blob
        except RateLimitedError as e:
            # keep the digests already found, but don't trust a partial result for version
            if local_image_info.index_name:
                self.throttle(local_image_info.index_name, e)
            result.throttled = True
            return None
        except (OCIError, ValueError) as e:
            self.log.warning("Failed to extract %s image info from config: %s", local_image_info.ref, e)
            return None

        registry_platform: Platform | None = image.platform
        if (
            registry_platform
            and local_image_info.os
            and (registry_platform.os != local_image_info.os or registry_platform.architecture != local_image_info.arch)
        ):
            self.log.warning(
                "Registry image %s is single platform %s, not matching local %s/%s",
                local_image_info.ref,
                registry_platform,
                local_image_info.os,
                local_image_info.arch,
            )
        result.annotations.update(image.labels)
        if isinstance(image.config, dict):
            result.annotations.update(image.config.get("annotations") or {})
        result.created = image.created
        return cache_metadata(blob.response)


class DockerClientVersionLookup(VersionLookup):
    """Query remote registry via local Docker API

    No auth needed, however uses the old v1 APIs, and only Index available via API
    """

    def __init__(self, client: docker.DockerClient, throttler: Throttler, cfg: RegistryConfig, api_backoff: int = 30) -> None:
        self.client: docker.DockerClient = client
        self.throttler: Throttler = throttler
        self.cfg: RegistryConfig = cfg
        self.api_backoff: int = api_backoff
        self.log: Any = structlog.get_logger().bind(integration="docker", tool="version_lookup")

    def lookup(self, local_image_info: DockerImageInfo, retries: int = 3, **kwargs: Any) -> DockerImageInfo:
        retries_left = retries
        retry_secs: int = self.api_backoff
        reg_data: RegistryData | None = None

        result = DockerImageInfo(local_image_info.ref)
        if local_image_info.index_name is None or local_image_info.ref is None:
            return result

        while reg_data is None and retries_left > 0:
            if self.throttler.check_throttle(local_image_info.index_name):
                result.throttled = True
                break
            try:
                self.log.debug("Fetching registry data", image_ref=local_image_info.ref)
                reg_data = self.client.images.get_registry_data(local_image_info.ref)
                self.log.debug(
                    "Registry Data: id:%s,image:%s, attrs:%s",
                    reg_data.id,
                    reg_data.image_name,
                    reg_data.attrs,
                )
                if reg_data:
                    result.short_digest = result.condense_digest(reg_data.short_id)
                    result.image_digest = result.condense_digest(reg_data.id, short=False)
                    # result.name = reg_data.image_name
                    result.attributes = reg_data.attrs
                    result.annotations = reg_data.attrs.get("Config", {}).get("Labels") or {}
                    result.error = None

            except docker.errors.APIError as e:
                if e.status_code == HTTPStatus.TOO_MANY_REQUESTS:
                    retry_secs = round(retry_secs**1.5)
                    try:
                        if e.response and e.response.headers:
                            retry_secs = int(e.response.headers.get("Retry-After", -1))
                    except Exception as e2:
                        self.log.debug("Failed to access headers for retry info: %s", e2)
                    self.throttler.throttle(local_image_info.index_name, retry_secs, e.explanation)
                    result.throttled = True
                    return result
                result.error = str(e)
                retries_left -= 1
                if retries_left == 0 or e.is_client_error():
                    self.log.warning("Failed to fetch registry data: [%s] %s", e.errno, e.explanation)
                else:
                    self.log.debug("Failed to fetch registry data, retrying: %s", e)

        labels: dict[str, str | float | int | bool | None] = cherrypick_annotations(local_image_info, result)
        result.custom = labels or {}
        result.version = cast("str|None", labels.get("image_version"))
        result.created = cast("str|None", labels.get("image_created"))
        result.origin = "DOCKER_CLIENT"
        return result
