import re
from typing import Any

import structlog
from docker.auth import resolve_repository_name
from hishel.httpx import SyncCacheClient
from httpx import Response
from omegaconf import MissingMandatoryValue, OmegaConf, ValidationError

from updates2mqtt.config import (
    NO_KNOWN_IMAGE,
    PKG_INFO_FILE,
    DockerConfig,
    DockerPackageUpdateInfo,
    PackageUpdateInfo,
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


def id_source_platform(source: str | None) -> str | None:
    candidates: list[str] = [platform for platform, pattern in SOURCE_PLATFORMS.items() if re.match(pattern, source or "")]
    return candidates[0] if candidates else None


class PackageEnricher:
    def __init__(self, docker_cfg: DockerConfig) -> None:
        self.pkgs: dict[str, PackageUpdateInfo] = {}
        self.cfg: DockerConfig = docker_cfg
        self.log: Any = structlog.get_logger().bind(integration="docker")

    def initialize(self) -> None:
        pass

    def enrich(self, image_name: str | None, image_ref: str | None, log: Any) -> PackageUpdateInfo | None:
        def match(pkg: PackageUpdateInfo) -> bool:
            if pkg is not None and pkg.docker is not None and pkg.docker.image_name is not None:
                if image_name is not None and image_name == pkg.docker.image_name:
                    return True
                if image_ref is not None and image_ref == pkg.docker.image_name:
                    return True
            return False

        if image_name is not None and image_ref is not None:
            for pkg in self.pkgs.values():
                if match(pkg):
                    log.debug(
                        "Found common package",
                        image_name=pkg.docker.image_name,  # type: ignore [union-attr]
                        logo_url=pkg.logo_url,
                        relnotes_url=pkg.release_notes_url,
                    )
                    return pkg
        return None


class DefaultPackageEnricher(PackageEnricher):
    def enrich(self, image_name: str | None, image_ref: str | None, log: Any) -> PackageUpdateInfo | None:
        log.debug("Default pkg info", image_name=image_name, image_ref=image_ref)
        return PackageUpdateInfo(
            DockerPackageUpdateInfo(image_name or NO_KNOWN_IMAGE),
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
    url: str, cache_ttl: int = 300, bearer_token: str | None = None, response_type: str | None = None
) -> Response | None:
    try:
        headers = [("cache-control", f"max-age={cache_ttl}")]
        if bearer_token:
            headers.append(("Authorization", f"Bearer {bearer_token}"))
        if response_type:
            headers.append(("Accept", response_type))
        with SyncCacheClient(headers=headers) as client:
            log.debug(f"Fetching URL {url}, cache_ttl={cache_ttl}")
            response: Response = client.get(url)
            if not response.is_success:
                log.debug("URL %s fetch returned non-success status: %s", url, response.status_code)
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

    def record(self, results: dict[str, str], k: str, v: str | None) -> None:
        if v is not None:
            results[k] = v

    def enrich(
        self, annotations: dict[str, str], source_repo_url: str | None = None, release_url: str | None = None
    ) -> dict[str, str]:
        results: dict[str, str] = {}

        self.record(results, "latest_image_created", annotations.get("org.opencontainers.image.created"))
        self.record(results, "documentation_url", annotations.get("org.opencontainers.image.documentation"))
        self.record(results, "description", annotations.get("org.opencontainers.image.description"))
        self.record(results, "vendor", annotations.get("org.opencontainers.image.vendor"))

        release_version: str | None = annotations.get("org.opencontainers.image.version")
        self.record(results, "latest_image_version", release_version)
        release_revision: str | None = annotations.get("org.opencontainers.image.revision")
        self.record(results, "latest_release_revision", release_revision)
        release_source: str | None = annotations.get("org.opencontainers.image.source") or source_repo_url
        self.record(results, "source", release_source)

        release_source_deep: str | None = release_source
        if release_source and "#" in release_source:
            release_source = release_source.split("#", 1)[0]
            self.log.debug("Simplifying %s from %s", release_source, release_source_deep)

        source_platform = id_source_platform(release_source)
        if not source_platform:
            self.log.debug("No known source platform found on container", source=release_source)
            return results

        results["source_platform"] = source_platform

        template_vars: dict[str, str | None] = {
            "version": release_version or MISSING_VAL,
            "revision": release_revision or MISSING_VAL,
            "repo": release_source or MISSING_VAL,
            "source": release_source_deep or MISSING_VAL,
        }

        diff_url = DIFF_URL_TEMPLATES[source_platform].format(**template_vars)
        if MISSING_VAL not in diff_url and validate_url(diff_url):
            results["diff_url"] = diff_url

        if release_url is None:
            release_url = RELEASE_URL_TEMPLATES[source_platform].format(**template_vars)

            if MISSING_VAL in release_url or not validate_url(release_url):
                release_url = UNKNOWN_RELEASE_URL_TEMPLATES[source_platform].format(**template_vars)
                if MISSING_VAL in release_url or not validate_url(release_url):
                    release_url = None

        self.record(results, "release_url", release_url)

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
        return results


class AuthError(Exception):
    pass


REGISTRIES = {
    # registry: (auth_host, api_host, service)
    "docker.io": ("auth.docker.io", "registry-1.docker.io", "registry.docker.io"),
    "mcr.microsoft.com": (None, "mcr.microsoft.com", "mcr.microsoft.com"),
    "ghcr.io": ("ghcr.io", "ghcr.io", "ghcr.io"),
    "lscr.io": ("ghcr.io", "lscr.io", "ghcr.io"),
    "codeberg.org": ("codeberg.org", "codeberg.org", "container_registry"),
}


def httpx_json_content(response: Response, default: Any = None) -> Any | None:
    if response and "json" in response.headers.get("content-type"):
        try:
            return response.json()
        except Exception:
            log.debug("Failed to parse JSON response: %s", response.text)
    return default


class LabelEnricher:
    def __init__(self) -> None:
        self.log: Any = structlog.get_logger().bind(integration="docker")

    def fetch_token(self, auth_host: str, service: str, image_name: str) -> str | None:
        logger = self.log.bind(image_name=image_name, action="auth_registry")
        auth_url: str = f"https://{auth_host}/token?scope=repository:{image_name}:pull&service={service}"
        response: Response | None = fetch_url(auth_url, cache_ttl=30)
        if response and response.is_success:
            api_data = httpx_json_content(response, {})
            token: str | None = api_data.get("token") if api_data else None
            if token:
                return token
            logger.warning("No token found in response for %s", auth_url)
            raise AuthError(f"No token found in response for {image_name}")

        logger.debug(
            "Non-success response fetching token: %s",
            (response and response.status_code) or None,
        )
        if response and response.status_code == 404:
            response = fetch_url(f"https://{auth_host}/v2/")
        if response and response.status_code == 401:
            auth = response.headers.get("www-authenticate")
            if not auth:
                logger.warning("No www-authenticate header found in 401 response for %s", auth_url)
                raise AuthError(f"No www-authenticate header found on 401 for {image_name}")
            match = re.search(r'realm="([^"]+)",service="([^"]+)",scope="([^"]+)"', auth)
            if not match:
                logger.warning("No realm/service/scope found in www-authenticate header for %s", auth_url)
                raise AuthError(f"No realm/service/scope found on 401 headers for {image_name}")

            realm, service, scope = match.groups()
            auth_url = f"{realm}?service={service}&scope={scope}"
            response = fetch_url(auth_url)
            if response and response.is_success:
                token_data = response.json()
                logger.debug("Fetched registry token")
                return token_data.get("token")

        logger.debug("Failed to fetch registry token")
        raise AuthError(f"Failed to fetch token for {image_name} at {auth_url}")

    def fetch_annotations(
        self,
        image_ref: str,
        os: str,
        arch: str,
        token: str | None = None,
        mutable_cache_ttl: int = 600,
        immutable_cache_ttl: int = 86400,
    ) -> dict[str, str]:
        logger = self.log.bind(image_ref=image_ref, action="enrich_registry")
        annotations: dict[str, str] = {}
        if token:
            logger.debug("Using provided token to fetch manifest for image %s", image_ref)
        registry, ref = resolve_repository_name(image_ref)
        default_host = (registry, registry, registry)
        auth_host: str | None = REGISTRIES.get(registry, default_host)[0]
        api_host: str | None = REGISTRIES.get(registry, default_host)[1]
        service: str = REGISTRIES.get(registry, default_host)[2]
        img_name = ref.split(":")[0] if ":" in ref else ref
        img_name = img_name if "/" in img_name else f"library/{img_name}"
        if auth_host is not None and token is None:
            token = self.fetch_token(auth_host, service, img_name)

        img_tag = ref.split(":")[1] if ":" in ref else "latest"
        img_tag = img_tag.split("@")[0] if "@" in img_tag else img_tag
        response: Response | None = fetch_url(
            f"https://{api_host}/v2/{img_name}/manifests/{img_tag}",
            cache_ttl=mutable_cache_ttl,
            bearer_token=token,
            response_type="application/vnd.oci.image.index.v1+json",
        )
        if response is None:
            logger.debug("Empty response for manifest for image")
            return annotations
        if not response.is_success:
            api_data = httpx_json_content(response, {})
            logger.warning(
                "Failed to fetch manifest: %s",
                api_data.get("errors") if api_data else response.text,
            )
            return annotations
        index = response.json()
        logger.debug(
            "INDEX %s manifests, %s annotations",
            len(index.get("manifests", [])),
            len(index.get("annotations", [])),
        )
        annotations = index.get("annotations", {})
        for m in index.get("manifests", []):
            platform_info = m.get("platform", {})
            if platform_info.get("os") == os and platform_info.get("architecture") == arch:
                digest = m.get("digest")
                media_type = m.get("mediaType")
                response = fetch_url(
                    f"https://{api_host}/v2/{img_name}/manifests/{digest}",
                    cache_ttl=immutable_cache_ttl,
                    bearer_token=token,
                    response_type=media_type,
                )
                if response and response.is_success:
                    api_data = httpx_json_content(response, None)
                    if api_data:
                        logger.debug(
                            "MANIFEST %s layers, %s annotations",
                            len(api_data.get("layers", [])),
                            len(api_data.get("annotations", [])),
                        )
                        if api_data.get("annotations"):
                            annotations.update(api_data.get("annotations", {}))
                        else:
                            logger.debug("No annotations found in manifest: %s", api_data)

        if not annotations:
            logger.debug("No annotations found from registry data")
        return annotations


r"""
https://ghcr.io/token\?scope\="repository:rhizomatics/updates2mqtt:pull"
https://ghcr.io/v2/rhizomatics/updates2mqtt/manifests/sha256:2c8edc1f9400ef02a93c3b754d4419082ceb5d049178c3a3968e3fd56caf7f29 Accept:application/vnd.oci.image.index.v1+json Accept:application/vnd.oci.image.manifest.v1+json Accept:application/vnd.docker.distribution.manifest.v2+json
https://ghcr.io/v2/rhizomatics/updates2mqtt/manifests/latest Accept:application/vnd.oci.image.index.v1+json Accept:application/vnd.oci.image.manifest.v1+json Accept:appli
"""  # noqa: E501
