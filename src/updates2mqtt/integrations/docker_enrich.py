import re
import typing
from abc import abstractmethod
from typing import Any

import structlog
from docker.auth import resolve_repository_name
from docker.models.containers import Container
from hishel.httpx import SyncCacheClient
from httpx import Response
from omegaconf import MissingMandatoryValue, OmegaConf, ValidationError

from updates2mqtt.helpers import ThrottledError, Throttler

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
    RegistryAccessPolicy,
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


class DockerImageInfo:
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
        self.platform: str | None = None
        self.custom: dict[str, str | None] = {}

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


def cherrypick_annotations(local_info: DockerImageInfo | None, registry_info: DockerImageInfo | None) -> dict[str, str | None]:
    """https://github.com/opencontainers/image-spec/blob/main/annotations.md"""
    results: dict[str, str | None] = {}
    for local_name, local_label in [
        ("current_image_created", "org.opencontainers.image.created"),
        ("current_image_version", "org.opencontainers.image.version"),
        ("current_image_revision", "org.opencontainers.image.revision"),
    ]:
        results.update(_select_annotation(local_name, local_label, local_info))
    for either_name, either_label in [
        ("documentation_url", "org.opencontainers.image.documentation"),
        ("description", "org.opencontainers.image.description"),
        ("title", "org.opencontainers.image.title"),
        ("vendor", "org.opencontainers.image.vendor"),
        ("licences", "org.opencontainers.image.licenses"),
        ("current_image_base", "org.opencontainers.image.base.name"),
    ]:
        results.update(_select_annotation(either_name, either_label, local_info, registry_info))

    for reg_name, reg_label in [
        ("latest_image_created", "org.opencontainers.image.created"),
        ("latest_image_version", "org.opencontainers.image.version"),
        ("latest_image_revision", "org.opencontainers.image.revision"),
        ("latest_image_base", "org.opencontainers.image.base.name"),
        ("source", "org.opencontainers.image.source"),
    ]:
        results.update(_select_annotation(reg_name, reg_label, registry_info))

    return results


class LocalContainerInfo:
    def __init__(self, registry_access: RegistryAccessPolicy) -> None:
        self.registry_access: RegistryAccessPolicy = registry_access

    def build_image_info(self, container: Container) -> DockerImageInfo:
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

        custom: dict[str, str | None] = cherrypick_annotations(image_info, None)
        # capture container labels/annotations, not image ones
        custom["compose_path"] = container.labels.get("com.docker.compose.project.working_dir")
        custom["compose_version"] = container.labels.get("com.docker.compose.version")
        custom["compose_service"] = container.labels.get("com.docker.compose.service")
        custom["container_name"] = container.name
        image_info.custom = custom
        image_info.version = custom.get("current_image_version")
        return image_info


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

        try:
            with SyncCacheClient(headers=[("cache-control", f"max-age={cfg.cache_ttl}")]) as client:
                log.debug(f"Fetching linuxserver.io metadata from API, cache_ttl={cfg.cache_ttl}")
                response: Response = client.get(
                    "https://api.linuxserver.io/api/v1/images?include_config=false&include_deprecated=false"
                )
                if response.status_code != 200:
                    log.error("Failed to fetch linuxserver.io metadata, non-200 response", status_code=response.status_code)
                    return
                api_data: Any = response.json()
                repos: list = api_data.get("data", {}).get("repositories", {}).get("linuxserver", [])
        except Exception:
            log.exception("Failed to fetch linuxserver.io metadata")
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


def fetch_url(
    url: str,
    cache_ttl: int = 300,
    bearer_token: str | None = None,
    response_type: str | list[str] | None = None,
    follow_redirects: bool = False,
) -> Response | None:
    try:
        headers = [("cache-control", f"max-age={cache_ttl}")]
        if bearer_token:
            headers.append(("Authorization", f"Bearer {bearer_token}"))
        if response_type:
            response_type = [response_type] if isinstance(response_type, str) else response_type
            if response_type and isinstance(response_type, (tuple, list)):
                headers.extend(("Accept", mime_type) for mime_type in response_type)
        with SyncCacheClient(headers=headers, follow_redirects=follow_redirects) as client:
            log.debug(f"Fetching URL {url}, cache_ttl={cache_ttl}")
            response: Response = client.get(url)
            if not response.is_success:
                log.debug("URL %s fetch returned non-success status: %s", url, response.status_code)
            elif response:
                log.debug(
                    "Registry response: content_type: %s, Docker API %s, Digest %s",
                    response.headers.get("Content-Type"),
                    response.headers.get(HEADER_DOCKER_API),
                    response.headers.get(HEADER_DOCKER_DIGEST),
                )

            return response
    except Exception as e:
        log.debug("URL %s failed to fetch: %s", url, e)
    return None


def validate_url(url: str, cache_ttl: int = 300) -> bool:
    response: Response | None = fetch_url(url, cache_ttl=cache_ttl)
    return response is not None and response.status_code != 404


class SourceReleaseEnricher:
    def __init__(self) -> None:
        self.log: Any = structlog.get_logger().bind(integration="docker")

    def enrich(
        self, registry_info: DockerImageInfo, source_repo_url: str | None = None, release_url: str | None = None
    ) -> dict[str, str | None]:
        results: dict[str, str | None] = cherrypick_annotations(None, registry_info=registry_info)

        release_version: str | None = registry_info.annotations.get("org.opencontainers.image.version")
        release_revision: str | None = registry_info.annotations.get("org.opencontainers.image.revision")
        release_source: str | None = registry_info.annotations.get("org.opencontainers.image.source") or source_repo_url

        release_source_deep: str | None = release_source
        if release_source and "#" in release_source:
            release_source = release_source.split("#", 1)[0]
            self.log.debug("Simplifying %s from %s", release_source, release_source_deep)

        source_platform = id_source_platform(release_source)
        if not source_platform:
            self.log.debug("No known source platform found on container", source=release_source)
            return results

        results["source_platform"] = source_platform
        results["source_repo"] = release_source

        template_vars: dict[str, str | None] = {
            "version": release_version or MISSING_VAL,
            "revision": release_revision or MISSING_VAL,
            "repo": release_source or MISSING_VAL,
            "source": release_source_deep or MISSING_VAL,
        }

        diff_url: str | None = DIFF_URL_TEMPLATES[source_platform].format(**template_vars)
        if diff_url and MISSING_VAL not in diff_url and validate_url(diff_url):
            results["diff_url"] = diff_url
        else:
            diff_url = None

        if release_url is None:
            release_url = RELEASE_URL_TEMPLATES[source_platform].format(**template_vars)

            if MISSING_VAL in release_url or not validate_url(release_url):
                release_url = UNKNOWN_RELEASE_URL_TEMPLATES[source_platform].format(**template_vars)
                if MISSING_VAL in release_url or not validate_url(release_url):
                    release_url = None
        if release_url is not None:
            results["release_url"] = release_url

        if source_platform == SOURCE_PLATFORM_GITHUB and release_source:
            base_api = release_source.replace("https://github.com", "https://api.github.com/repos")

            api_response: Response | None = fetch_url(f"{base_api}/releases/tags/{release_version}")
            if api_response and api_response.is_success:
                api_results: Any = httpx_json_content(api_response, {})
                results["release_summary"] = api_results.get("body")  # ty:ignore[possibly-missing-attribute]
                reactions = api_results.get("reactions")  # ty:ignore[possibly-missing-attribute]
                if reactions:
                    results["net_score"] = reactions.get("+1", 0) - reactions.get("-1", 0)
            else:
                self.log.debug(
                    "Failed to fetch GitHub release info",
                    url=f"{base_api}/releases/tags/{release_version}",
                    status_code=(api_response and api_response.status_code) or None,
                )
        if not results.get("release_summary") and diff_url:
            results["release_summary"] = f"<a href='{diff_url}'>{release_version or release_revision} Diff</a>"
        return results


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
    def __init__(self, throttler: Throttler) -> None:
        self.throttler: Throttler = throttler
        self.log: Any = structlog.get_logger().bind(integration="docker", tool="version_lookup")

    def fetch_token(self, registry: str, image_name: str) -> str | None:
        default_host: tuple[str, str, str, str] = (registry, registry, registry, TOKEN_URL_TEMPLATE)
        auth_host: str | None = REGISTRIES.get(registry, default_host)[0]
        if auth_host is None:
            return None

        service: str = REGISTRIES.get(registry, default_host)[2]
        url_template: str = REGISTRIES.get(registry, default_host)[3]
        auth_url: str = url_template.format(auth_host=auth_host, image_name=image_name, service=service)
        response: Response | None = fetch_url(auth_url, cache_ttl=30, follow_redirects=True)
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
        self, api_host: str, local_image_info: DockerImageInfo, token: str | None, mutable_cache_ttl: int = 600
    ) -> tuple[Any | None, str | None]:
        api_url: str = f"https://{api_host}/v2/{local_image_info.name}/manifests/{local_image_info.tag_or_digest}"
        response: Response | None = fetch_url(
            api_url,
            cache_ttl=mutable_cache_ttl,
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
            return index, response.headers.get(HEADER_DOCKER_DIGEST)
        return None, None

    def fetch_manifest(
        self,
        api_host: str,
        local_image_info: DockerImageInfo,
        media_type: str,
        digest: str,
        token: str | None,
        immutable_cache_ttl: int = 86400,
    ) -> Any | None:
        api_url = f"https://{api_host}/v2/{local_image_info.name}/manifests/{digest}"
        response = fetch_url(
            api_url,
            cache_ttl=immutable_cache_ttl,
            bearer_token=token,
            response_type=media_type,
        )
        if response and response.is_success:
            manifest = httpx_json_content(response, None)
            if manifest:
                self.log.debug(
                    "MANIFEST %s, header digest:%s, api: %s, %s layers, %s annotations",
                    digest,
                    response.headers.get(HEADER_DOCKER_DIGEST, "N/A"),
                    response.headers.get(HEADER_DOCKER_API, "N/A"),
                    len(manifest.get("layers", [])),
                    len(manifest.get("annotations", [])),
                )
                return manifest
        elif response and response.status_code == 429:
            self.throttler.throttle(local_image_info.index_name, raise_exception=True)
        elif response and not response.is_success:
            api_data = httpx_json_content(response, {})
            self.log.warning(
                "Failed to fetch manifest from %s: %s", api_url, api_data.get("errors") if api_data else response.text
            )
        else:
            self.log.error("Empty response from %s", api_url)
        return None

    def lookup(
        self,
        local_image_info: DockerImageInfo,
        token: str | None = None,
        mutable_cache_ttl: int = 600,
        immutable_cache_ttl: int = 86400,
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
        api_host: str | None = REGISTRIES.get(
            local_image_info.index_name, (local_image_info.index_name, local_image_info.index_name)
        )[1]
        if api_host is None:
            self.log("No API host can be determined for %s", local_image_info.index_name)
            return result
        try:
            index, index_digest = self.fetch_index(api_host, local_image_info, token, mutable_cache_ttl)
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
                        log.debug("Setting image digest %s for %s", result.short_digest, result.name)

                    digest: str | None = m.get("digest")
                    media_type = m.get("mediaType")
                    manifest: Any | None = None
                    if digest:
                        try:
                            manifest = self.fetch_manifest(
                                api_host, local_image_info, media_type, digest, token, immutable_cache_ttl
                            )
                        except ThrottledError:
                            result.throttled = True

                    if manifest:
                        digest = manifest.get("config", {}).get("digest")
                        if digest is None:
                            self.log.warning("Empty digest for %s %s %s", api_host, digest, media_type)
                        else:
                            result.repo_digest = result.condense_digest(digest, short=False)

                        if manifest.get("annotations"):
                            result.annotations.update(manifest.get("annotations", {}))
                        else:
                            self.log.debug("No annotations found in manifest: %s", manifest)

        if not result.annotations:
            self.log.debug("No annotations found from registry data")

        custom: dict[str, str | None] = cherrypick_annotations(local_image_info, result)
        result.custom = custom
        result.version = custom.get("latest_image_version")
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

    def __init__(self, client: docker.DockerClient, throttler: Throttler, api_backoff: int = 30) -> None:
        self.client: docker.DockerClient = client
        self.throttler: Throttler = throttler
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

        custom: dict[str, str | None] = cherrypick_annotations(local_image_info, result)
        result.custom = custom
        result.version = custom.get("latest_image_version")
        result.origin = "DOCKER_CLIENT"
        return result
