import re
import typing
from abc import abstractmethod
from typing import Any, cast

import structlog
from docker.auth import resolve_repository_name
from docker.models.containers import Container
from httpx import Response
from omegaconf import MissingMandatoryValue, OmegaConf, ValidationError

from updates2mqtt.helpers import CacheMetadata, ThrottledError, Throttler, fetch_url, validate_url
from updates2mqtt.model import DiscoveryArtefactDetail, DiscoveryInstallationDetail, ReleaseDetail

if typing.TYPE_CHECKING:
    from docker.models.images import RegistryData
from http import HTTPStatus

import docker
import docker.errors

from updates2mqtt.config import (
    PKG_INFO_FILE,
    DockerConfig,
    DockerPackageUpdateInfo,
    PackageUpdateInfo,
    RegistryConfig,
    UpdateInfoConfig,
)

log = structlog.get_logger()

SOURCE_PLATFORM_GITHUB = "GitHub"
SOURCE_PLATFORM_CODEBERG = "CodeBerg"
SOURCE_PLATFORMS = {SOURCE_PLATFORM_GITHUB: r"https://github.com/.*"}
DIFF_URL_TEMPLATES = {
    SOURCE_PLATFORM_GITHUB: "{repo}/commit/{revision}",
}
RELEASE_URL_TEMPLATES = {SOURCE_PLATFORM_GITHUB: "{repo}/releases/tag/{version}"}
UNKNOWN_RELEASE_URL_TEMPLATES = {SOURCE_PLATFORM_GITHUB: "{repo}/releases"}
MISSING_VAL = "**MISSING**"
UNKNOWN_REGISTRY = "**UNKNOWN_REGISTRY**"

HEADER_DOCKER_DIGEST = "docker-content-digest"
HEADER_DOCKER_API = "docker-distribution-api-version"

TOKEN_URL_TEMPLATE = "https://{auth_host}/token?scope=repository:{image_name}:pull&service={service}"  # noqa: S105 # nosec
REGISTRIES = {
    # registry: (auth_host, api_host, service, url_template)
    "docker.io": ("auth.docker.io", "registry-1.docker.io", "registry.docker.io", TOKEN_URL_TEMPLATE),
    "mcr.microsoft.com": (None, "mcr.microsoft.com", "mcr.microsoft.com", TOKEN_URL_TEMPLATE),
    "ghcr.io": ("ghcr.io", "ghcr.io", "ghcr.io", TOKEN_URL_TEMPLATE),
    "lscr.io": ("ghcr.io", "lscr.io", "ghcr.io", TOKEN_URL_TEMPLATE),
    "codeberg.org": ("codeberg.org", "codeberg.org", "container_registry", TOKEN_URL_TEMPLATE),
    "registry.gitlab.com": (
        "www.gitlab.com",
        "registry.gitlab.com",
        "container_registry",
        "https://{auth_host}/jwt/auth?service={service}&scope=repository:{image_name}:pull&offline_token=true&client_id=docker",
    ),
}

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
    ) -> None:
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

        if self.os and self.arch:
            self.platform = "/".join(
                filter(
                    None,
                    [self.os, self.arch, self.variant],
                ),
            )

        if self.image_digest is not None:
            self.image_digest = self.condense_digest(self.image_digest, short=False)
            self.short_digest = self.condense_digest(self.image_digest)  # type: ignore[arg-type]

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

    def condense_digest(self, digest: str, short: bool = True) -> str | None:
        try:
            digest = digest.split("@")[1] if "@" in digest else digest  # fully qualified RepoDigest
            if short:
                digest = digest.split(":")[1] if ":" in digest else digest  # remove digest type prefix
                return digest[0:12]
            return digest
        except Exception:
            return None

    def reuse(self) -> "DockerImageInfo":
        cloned = DockerImageInfo(self.ref, self.image_digest, self.tags, self.attributes, self.annotations, self.version)
        cloned.origin = "REUSED"
        return cloned

    def as_dict(self, minimal: bool = True) -> dict[str, str | list | dict | bool | int | None]:
        result: dict[str, str | list | dict | bool | int | None] = {
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
    local_info: DockerImageInfo | None, registry_info: DockerImageInfo | None
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
        ("title", "org.opencontainers.image.title"),
        ("vendor", "org.opencontainers.image.vendor"),
        ("source", "org.opencontainers.image.source"),
    ]:
        results.update(_select_annotation(either_name, either_label, local_info, registry_info))
    return results


class DockerServiceDetails(DiscoveryInstallationDetail):
    def __init__(
        self,
        container_name: str | None = None,
        compose_path: str | None = None,
        compose_version: str | None = None,
        compose_service: str | None = None,
        git_repo_path: str | None = None,
    ) -> None:
        self.container_name: str | None = container_name
        self.compose_path: str | None = compose_path
        self.compose_version: str | None = compose_version
        self.compose_service: str | None = compose_service
        self.git_repo_path: str | None = git_repo_path
        self.git_local_timestamp: str | None = None

    def as_dict(self) -> dict[str, str | list | dict | bool | int | None]:
        results: dict[str, str | list | dict | bool | int | None] = {
            "container_name": self.container_name,
            "compose_path": self.compose_path,
            "compose_service": self.compose_service,
            "compose_version": self.compose_version,
        }
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
        image_ref: str = container.attrs.get("Config", {}).get("Image") or ""
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
        )

        labels: dict[str, str | float | int | bool | None] = cherrypick_annotations(image_info, None)
        # capture container labels/annotations, not image ones
        labels = labels or {}
        image_info.custom = labels
        image_info.version = cast("str|None", labels.get("image_version"))
        return image_info, service_info


class PackageEnricher:
    def __init__(self, docker_cfg: DockerConfig) -> None:
        self.pkgs: dict[str, PackageUpdateInfo] = {}
        self.cfg: DockerConfig = docker_cfg
        self.log: Any = structlog.get_logger().bind(integration="docker")

    def initialize(self) -> None:
        pass

    def enrich(self, image_info: DockerImageInfo) -> PackageUpdateInfo | None:
        def match(pkg: PackageUpdateInfo) -> bool:
            if pkg is not None and pkg.docker is not None and pkg.docker.image_name is not None:
                if image_info.untagged_ref is not None and image_info.untagged_ref == pkg.docker.image_name:
                    return True
                if image_info.ref is not None and image_info.ref == pkg.docker.image_name:
                    return True
            return False

        if image_info.untagged_ref is not None and image_info.ref is not None:
            for pkg in self.pkgs.values():
                if match(pkg):
                    self.log.debug(
                        "Found common package",
                        image_name=pkg.docker.image_name,  # type: ignore [union-attr]
                        logo_url=pkg.logo_url,
                        relnotes_url=pkg.release_notes_url,
                    )
                    return pkg
        return None


class DefaultPackageEnricher(PackageEnricher):
    def enrich(self, image_info: DockerImageInfo) -> PackageUpdateInfo | None:
        self.log.debug("Default pkg info", image_name=image_info.untagged_ref, image_ref=image_info.ref)
        return PackageUpdateInfo(
            DockerPackageUpdateInfo(image_info.untagged_ref or image_info.ref),
            logo_url=self.cfg.default_entity_picture_url,
            release_notes_url=None,
        )


class CommonPackageEnricher(PackageEnricher):
    def initialize(self) -> None:
        if PKG_INFO_FILE.exists():
            log.debug("Loading common package update info", path=PKG_INFO_FILE)
            cfg = OmegaConf.load(PKG_INFO_FILE)
        else:
            log.warn("No common package update info found", path=PKG_INFO_FILE)
            cfg = OmegaConf.structured(UpdateInfoConfig)
        try:
            # omegaconf broken-ness on optional fields and converting to backclasses
            self.pkgs: dict[str, PackageUpdateInfo] = {
                pkg: PackageUpdateInfo(**pkg_cfg) for pkg, pkg_cfg in cfg.common_packages.items()
            }
        except (MissingMandatoryValue, ValidationError) as e:
            log.error("Configuration error %s", e, path=PKG_INFO_FILE.as_posix())
            raise


class LinuxServerIOPackageEnricher(PackageEnricher):
    def initialize(self) -> None:
        cfg = self.cfg.discover_metadata.get("linuxserver.io")
        if cfg is None or not cfg.enabled:
            return

        log.debug(f"Fetching linuxserver.io metadata from API, cache_ttl={cfg.cache_ttl}")
        response: Response | None = fetch_url(
            "https://api.linuxserver.io/api/v1/images?include_config=false&include_deprecated=false",
            cache_ttl=cfg.cache_ttl,
        )
        if response and response.is_success:
            api_data: Any = response.json()
            repos: list = api_data.get("data", {}).get("repositories", {}).get("linuxserver", [])
        else:
            return

        added = 0
        for repo in repos:
            image_name = repo.get("name")
            if image_name and image_name not in self.pkgs:
                self.pkgs[image_name] = PackageUpdateInfo(
                    DockerPackageUpdateInfo(f"lscr.io/linuxserver/{image_name}"),
                    logo_url=repo["project_logo"],
                    release_notes_url=f"{repo['github_url']}/releases",
                )
                added += 1
                log.debug("Added linuxserver.io package", pkg=image_name)
        log.info(f"Added {added} linuxserver.io package details")


class SourceReleaseEnricher:
    def __init__(self) -> None:
        self.log: Any = structlog.get_logger().bind(integration="docker")

    def enrich(
        self, registry_info: DockerImageInfo, source_repo_url: str | None = None, notes_url: str | None = None
    ) -> ReleaseDetail | None:
        if not registry_info.annotations and not source_repo_url and not notes_url:
            return None

        detail = ReleaseDetail()

        detail.notes_url = notes_url
        detail.version = registry_info.annotations.get("org.opencontainers.image.version")
        detail.revision = registry_info.annotations.get("org.opencontainers.image.revision")
        detail.source_url = registry_info.annotations.get("org.opencontainers.image.source") or source_repo_url

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

        diff_url: str | None = DIFF_URL_TEMPLATES[detail.source_platform].format(**template_vars)
        if diff_url and MISSING_VAL not in diff_url and validate_url(diff_url):
            detail.diff_url = diff_url
        else:
            diff_url = None

        if detail.notes_url is None:
            detail.notes_url = RELEASE_URL_TEMPLATES[detail.source_platform].format(**template_vars)

            if MISSING_VAL in detail.notes_url or not validate_url(detail.notes_url):
                detail.notes_url = UNKNOWN_RELEASE_URL_TEMPLATES[detail.source_platform].format(**template_vars)
                if MISSING_VAL in detail.notes_url or not validate_url(detail.notes_url):
                    detail.notes_url = None

        if detail.source_platform == SOURCE_PLATFORM_GITHUB and detail.source_repo_url:
            base_api = detail.source_repo_url.replace("https://github.com", "https://api.github.com/repos")

            api_response: Response | None = fetch_url(f"{base_api}/releases/tags/{detail.version}")
            if api_response and api_response.is_success:
                api_results: Any = httpx_json_content(api_response, {})
                detail.summary = api_results.get("body")  # ty:ignore[possibly-missing-attribute]
                reactions = api_results.get("reactions")  # ty:ignore[possibly-missing-attribute]
                if reactions:
                    detail.net_score = reactions.get("+1", 0) - reactions.get("-1", 0)
            else:
                self.log.debug(
                    "Failed to fetch GitHub release info",
                    url=f"{base_api}/releases/tags/{detail.version}",
                    status_code=(api_response and api_response.status_code) or None,
                )
        if not detail.summary and detail.diff_url:
            detail.summary = f"<a href='{detail.diff_url}'>{detail.version or detail.revision} Diff</a>"
        return detail


class AuthError(Exception):
    pass


def httpx_json_content(response: Response, default: Any = None) -> Any | None:
    if response and "json" in response.headers.get("content-type", ""):
        try:
            return response.json()
        except Exception:
            log.debug("Failed to parse JSON response: %s", response.text)
    return default


class VersionLookup:
    def __init__(self) -> None:
        self.log: Any = structlog.get_logger().bind(integration="docker", tool="version_lookup")

    @abstractmethod
    def lookup(self, local_image_info: DockerImageInfo, **kwargs) -> DockerImageInfo:  # noqa: ANN003
        pass


class ContainerDistributionAPIVersionLookup(VersionLookup):
    def __init__(self, throttler: Throttler, cfg: RegistryConfig) -> None:
        self.throttler: Throttler = throttler
        self.cfg: RegistryConfig = cfg
        self.log: Any = structlog.get_logger().bind(integration="docker", tool="version_lookup")

    def fetch_token(self, registry: str, image_name: str) -> str | None:
        default_host: tuple[str, str, str, str] = (registry, registry, registry, TOKEN_URL_TEMPLATE)
        auth_host: str | None = REGISTRIES.get(registry, default_host)[0]
        if auth_host is None:
            return None

        service: str = REGISTRIES.get(registry, default_host)[2]
        url_template: str = REGISTRIES.get(registry, default_host)[3]
        auth_url: str = url_template.format(auth_host=auth_host, image_name=image_name, service=service)
        response: Response | None = fetch_url(auth_url, cache_ttl=self.cfg.token_cache_ttl, follow_redirects=True)
        if response and response.is_success:
            api_data = httpx_json_content(response, {})
            token: str | None = api_data.get("token") if api_data else None
            if token:
                return token
            self.log.warning("No token found in response for %s", auth_url)
            raise AuthError(f"No token found in response for {image_name}")

        self.log.debug(
            "Non-success response at %s fetching token: %s",
            auth_url,
            (response and response.status_code) or None,
        )
        if response and response.status_code == 404:
            self.log.debug(
                "Default token URL %s not found, calling /v2 endpoint to validate OCI API and provoke auth", auth_url
            )
            response = fetch_url(f"https://{auth_host}/v2", follow_redirects=True)

        if response and response.status_code == 401:
            auth = response.headers.get("www-authenticate")
            if not auth:
                self.log.warning("No www-authenticate header found in 401 response for %s", auth_url)
                raise AuthError(f"No www-authenticate header found on 401 for {image_name}")
            match = re.search(r'realm="([^"]+)",service="([^"]+)",scope="([^"]+)"', auth)
            if not match:
                self.log.warning("No realm/service/scope found in www-authenticate header for %s", auth_url)
                raise AuthError(f"No realm/service/scope found on 401 headers for {image_name}")

            realm, service, scope = match.groups()
            auth_url = f"{realm}?service={service}&scope={scope}"
            response = fetch_url(auth_url, follow_redirects=True)
            if response and response.is_success:
                token_data = response.json()
                self.log.debug("Fetched registry token from %s", auth_url)
                return token_data.get("token")
            self.log.warning(
                "Alternative auth %s with status %s has no token", auth_url, (response and response.status_code) or None
            )
        elif response:
            self.log.warning("Auth %s failed with status %s", auth_url, (response and response.status_code) or None)

        raise AuthError(f"Failed to fetch token for {image_name} at {auth_url}")

    def fetch_index(
        self, api_host: str, local_image_info: DockerImageInfo, token: str | None
    ) -> tuple[Any | None, str | None, CacheMetadata | None]:
        if local_image_info.tag:
            api_url: str = f"https://{api_host}/v2/{local_image_info.name}/manifests/{local_image_info.tag}"
            cache_ttl: int | None = self.cfg.mutable_cache_ttl
        else:
            api_url = f"https://{api_host}/v2/{local_image_info.name}/manifests/{local_image_info.pinned_digest}"
            cache_ttl = self.cfg.immutable_cache_ttl

        response: Response | None = fetch_url(
            api_url,
            cache_ttl=cache_ttl,
            bearer_token=token,
            response_type=[
                "application/vnd.oci.image.index.v1+json",
                "application/vnd.docker.distribution.manifest.list.v2+json",
            ],
        )
        if response is None:
            self.log.warning("Empty response for manifest for image at %s", api_url)
        elif response.status_code == 429:
            self.throttler.throttle(local_image_info.index_name, raise_exception=True)
        elif not response.is_success:
            api_data = httpx_json_content(response, {})
            self.log.warning(
                "Failed to fetch index from %s: %s",
                api_url,
                api_data.get("errors") if api_data else response.text,
            )
        else:
            index = response.json()
            self.log.debug(
                "INDEX %s manifests, %s annotations, api: %s, header digest: %s",
                len(index.get("manifests", [])),
                len(index.get("annotations", [])),
                response.headers.get(HEADER_DOCKER_API, "N/A"),
                response.headers.get(HEADER_DOCKER_DIGEST, "N/A"),
            )
            return index, response.headers.get(HEADER_DOCKER_DIGEST), CacheMetadata(response)
        return None, None, None

    def fetch_object(
        self,
        api_host: str,
        local_image_info: DockerImageInfo,
        media_type: str,
        digest: str,
        token: str | None,
        api_type: str = "manifests",
    ) -> tuple[Any | None, CacheMetadata | None]:
        api_url = f"https://{api_host}/v2/{local_image_info.name}/{api_type}/{digest}"
        response = fetch_url(
            api_url, cache_ttl=self.cfg.immutable_cache_ttl, bearer_token=token, response_type=media_type, allow_stale=True
        )
        if response and response.is_success:
            obj = httpx_json_content(response, None)
            if obj:
                self.log.debug(
                    "%s, header digest:%s, api: %s, %s annotations",
                    api_type.upper(),
                    response.headers.get(HEADER_DOCKER_DIGEST, "N/A"),
                    response.headers.get(HEADER_DOCKER_API, "N/A"),
                    len(obj.get("annotations", [])),
                )
                return obj, CacheMetadata(response)
        elif response and response.status_code == 429:
            self.throttler.throttle(local_image_info.index_name, raise_exception=True)
        elif response and not response.is_success:
            api_data = httpx_json_content(response, {})
            if response:
                self.log.warning(
                    "Failed to fetch obj from %s: %s %s",
                    api_url,
                    response.status_code,
                    api_data.get("errors") if api_data else response.text,
                )
            else:
                self.log.warning(
                    "Failed to fetch obj from %s: No Response, %s", api_url, api_data.get("errors") if api_data else None
                )

        else:
            self.log.error("Empty response from %s", api_url)
        return None, None

    def lookup(
        self,
        local_image_info: DockerImageInfo,
        token: str | None = None,
        **kwargs,  # noqa: ANN003, ARG002
    ) -> DockerImageInfo:
        result: DockerImageInfo = DockerImageInfo(local_image_info.ref)
        if not local_image_info.name or not local_image_info.index_name:
            self.log.debug("No local pkg name or registry index name to check")
            return result

        if self.throttler.check_throttle(local_image_info.index_name):
            result.throttled = True
            return result

        if token:
            self.log.debug("Using provided token to fetch manifest for image %s", local_image_info.ref)
        else:
            try:
                token = self.fetch_token(local_image_info.index_name, local_image_info.name)
            except AuthError as e:
                self.log.warning("Authentication error prevented Docker Registry enrichment: %s", e)
                result.error = str(e)
                return result

        index: Any | None = None
        index_digest: str | None = None  # fetched from header, should be the image digest
        index_cache_metadata: CacheMetadata | None = None
        manifest_cache_metadata: CacheMetadata | None = None
        api_host: str | None = REGISTRIES.get(
            local_image_info.index_name, (local_image_info.index_name, local_image_info.index_name)
        )[1]
        if api_host is None:
            self.log("No API host can be determined for %s", local_image_info.index_name)
            return result
        try:
            index, index_digest, index_cache_metadata = self.fetch_index(api_host, local_image_info, token)
        except ThrottledError:
            result.throttled = True
            index = None

        if index:
            result.annotations = index.get("annotations", {})
            for m in index.get("manifests", []):
                platform_info = m.get("platform", {})
                if (
                    platform_info.get("os") == local_image_info.os
                    and platform_info.get("architecture") == local_image_info.arch
                    and ("Variant" not in platform_info or platform_info.get("Variant") == local_image_info.variant)
                ):
                    if index_digest:
                        result.image_digest = index_digest
                        result.short_digest = result.condense_digest(index_digest)
                        log.debug("Setting %s image digest %s", result.name, result.short_digest)

                    digest: str | None = m.get("digest")
                    media_type = m.get("mediaType")
                    manifest: Any | None = None

                    if digest:
                        try:
                            manifest, manifest_cache_metadata = self.fetch_object(
                                api_host, local_image_info, media_type, digest, token
                            )
                        except ThrottledError:
                            result.throttled = True

                    if manifest:
                        digest = manifest.get("config", {}).get("digest")
                        if digest is None:
                            self.log.warning("Empty digest for %s %s %s", api_host, digest, media_type)
                        else:
                            result.repo_digest = result.condense_digest(digest, short=False)
                            log.debug("Setting %s repo digest: %s", result.name, result.repo_digest)

                        if manifest.get("annotations"):
                            result.annotations.update(manifest.get("annotations", {}))
                        else:
                            self.log.debug("No annotations found in manifest: %s", manifest)

                        if manifest.get("config"):
                            config, _config_cache = self.fetch_object(
                                api_host,
                                local_image_info,
                                manifest["config"].get("mediaType"),
                                digest=manifest["config"].get("digest"),
                                token=token,
                                api_type="blobs",
                            )
                            if config:
                                result.annotations.update(config.get("annotations", {}))
                            else:
                                self.log.debug("No annotations found in config: %s", manifest)

        if not result.annotations:
            self.log.debug("No annotations found from registry data")

        labels: dict[str, str | float | int | bool | None] = cherrypick_annotations(local_image_info, result)
        result.custom = labels or {}
        if index_cache_metadata:
            result.custom["index_cache_age"] = index_cache_metadata.age
        if manifest_cache_metadata:
            result.custom["manifest_cache_age"] = manifest_cache_metadata.age
        result.version = cast("str|None", labels.get("image_version"))
        result.origin = "OCI_V2"

        self.log.debug(
            "OCI_V2 Lookup for %s: short_digest:%s, repo_digest:%s, version: %s",
            local_image_info.name,
            result.short_digest,
            result.repo_digest,
            result.version,
        )
        return result


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

    def lookup(self, local_image_info: DockerImageInfo, retries: int = 3, **kwargs) -> DockerImageInfo:  # noqa: ANN003, ARG002
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
                        retry_secs = int(e.response.headers.get("Retry-After", -1))  # type: ignore[union-attr]
                    except Exception as e2:
                        self.log.debug("Failed to access headers for retry info: %s", e2)
                    self.throttler.throttle(local_image_info.index_name, retry_secs, e.explanation)
                    result.throttled = True
                    return result
                result.error = str(e)
                retries_left -= 1
                if retries_left == 0 or e.is_client_error():
                    self.log.warn("Failed to fetch registry data: [%s] %s", e.errno, e.explanation)
                else:
                    self.log.debug("Failed to fetch registry data, retrying: %s", e)

        labels: dict[str, str | float | int | bool | None] = cherrypick_annotations(local_image_info, result)
        result.custom = labels or {}
        result.version = cast("str|None", labels.get("image_version"))
        result.origin = "DOCKER_CLIENT"
        return result
