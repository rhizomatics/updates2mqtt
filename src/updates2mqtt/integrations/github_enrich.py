import re
from typing import TYPE_CHECKING, Any

import structlog

from updates2mqtt.config import (
    VERSION_RE,
    GitHubConfig,
)
from updates2mqtt.helpers import fetch_url, httpx_json_content
from updates2mqtt.integrations.docker_enrich import REGISTRY_GHCR, DockerImageInfo
from updates2mqtt.model import ReleaseDetail

if TYPE_CHECKING:
    from httpx import Response

log: Any = structlog.get_logger()


class GithubReleaseEnricher:
    def __init__(self, gh_cfg: GitHubConfig) -> None:
        self.log: Any = structlog.get_logger().bind(integration="github")
        self.gh_cfg: GitHubConfig = gh_cfg
        self.gh_token: str | None = self.gh_cfg.access_token
        if self.gh_token:
            self.log.debug("Using configured bearer token (%s chars) for GitHub API", len(self.gh_token))

    def enrich(self, image: DockerImageInfo, detail: ReleaseDetail) -> None:

        if not detail.source_repo_url or not image.name:
            return

        if not detail.version or not re.fullmatch(VERSION_RE, detail.version):
            self.log.debug("No valid version found for GitHub release %s: %s", image.name, detail.version)
            if image.image_digest and image.index_name == REGISTRY_GHCR:
                matched = self.match_packages(image.unqualified_name, image.image_digest, detail.source_repo_url)
                if matched:
                    tags: list[str]
                    _release_url: str | None
                    created_ts: str | None
                    updated_ts: str | None
                    tags, _release_url, created_ts, updated_ts = matched
                    for t in tags:
                        if re.fullmatch(VERSION_RE, t):
                            self.log.debug(
                                "Matched %s version %s created on %s last updated %s", image.name, t, created_ts, updated_ts
                            )
                            detail.version = t

        if detail.version is not None:
            base_api = detail.source_repo_url.replace("https://github.com", "https://api.github.com/repos")

            api_response: Response | None = fetch_url(
                f"{base_api}/releases/tags/{detail.version}",
                bearer_token=self.gh_token,
                cache_ttl=self.gh_cfg.mutable_cache_ttl,
                allow_stale=True,  # not assuming immutable tags
            )
            if api_response and api_response.status_code == 404:
                # possible that source version doesn't match release gag
                alt_api_response: Response | None = fetch_url(
                    f"{base_api}/releases/latest",
                    cache_ttl=self.gh_cfg.mutable_cache_ttl,
                    bearer_token=self.gh_token,
                )
                if alt_api_response and alt_api_response.is_success:
                    alt_api_results = httpx_json_content(alt_api_response, {})
                    if alt_api_results and re.fullmatch(f"(V|v|r|R)?{detail.version}", alt_api_results.get("tag_name")):
                        self.log.info(f"Matched {image.name} {detail.version} to latest release {alt_api_results['tag_name']}")
                        api_response = alt_api_response
                    elif alt_api_results:
                        self.log.debug(
                            "Failed to match %s release %s on GitHub, found tag %s for name %s published at %s",
                            image.name,
                            detail.version,
                            alt_api_results.get("tag_name"),
                            alt_api_results.get("name"),
                            alt_api_results.get("published_at"),
                        )

            if api_response and api_response.is_success:
                api_results: Any = httpx_json_content(api_response, {})
                detail.summary = api_results.get("body")  # ty:ignore[possibly-missing-attribute]
                reactions = api_results.get("reactions")  # ty:ignore[possibly-missing-attribute]
                if reactions:
                    detail.net_score = reactions.get("+1", 0) - reactions.get("-1", 0)
                return
            if api_response:
                api_results = httpx_json_content(api_response, default={})
                self.log.debug(
                    "Failed to find %s release %s on GitHub, status %s, errors; %s",
                    image.name,
                    detail.version,
                    api_response.status_code,
                    api_results.get("errors"),
                )
            else:
                self.log.debug(
                    "Failed to fetch GitHub release info",
                    url=f"{base_api}/releases/tags/{detail.version}",
                    status_code=(api_response and api_response.status_code) or None,
                )

    def match_packages(
        self, package: str, package_digest: str, source_repo_url: str
    ) -> tuple[list[str], str | None, str | None, str | None] | None:

        if not self.gh_token:
            self.log.debug("No access token available for packages API")
            return None

        match = re.match(r"https://github\.com/([^/]+)/(?:[^/]+?)(?:\.git)?$", source_repo_url)
        if not match:
            self.log.debug("Invalid source repo URL for GitHub API use: %s", source_repo_url)
            return None
        org_or_user: str = match.group(1)

        api_result: Response | None = fetch_url(
            f"https://api.github.com/orgs/{org_or_user}/packages/container/{package}/versions",
            cache_ttl=self.gh_cfg.mutable_cache_ttl,
            bearer_token=self.gh_token,
        )
        if api_result and api_result.status_code == 404:
            api_result = fetch_url(
                f"https://api.github.com/users/{org_or_user}/packages/container/{package}/versions",
                cache_ttl=self.gh_cfg.mutable_cache_ttl,
                bearer_token=self.gh_token,
            )
        if not api_result:
            self.log.warn("Unable to retrieve GitHub packages API result, null response")
            return None
        if not api_result.is_success:
            self.log.warn(
                "Unable to retrieve GitHub packages API result, %s response: %s", api_result.status_code, api_result.text
            )
            if api_result.status_code == 401:
                self.log.warn("Disabling Github access token for this session")
                self.gh_token = None
            return None

        pkg_releases = api_result.json()
        for release in pkg_releases:
            if release.get("name") == package_digest:
                self.log.info(
                    "Matched %s image digest using GitHub API for release %s, metadata %s",
                    package,
                    release.get("id"),
                    release.get("metadata"),
                )
                return (
                    release.get("metadata", {}).get("container", {}).get("tags", []),
                    release.get("html_url"),
                    release.get("created_at"),
                    release.get("updated_at"),
                )
        self.log.debug("No matching %s release found using GitHub API for %s", package, package_digest)
        return None
