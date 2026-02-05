from typing import TYPE_CHECKING

import structlog
from omegaconf import DictConfig, OmegaConf
from rich import print_json
from rich.console import Console

from updates2mqtt.config import DockerConfig, GitHubConfig, NodeConfig, RegistryConfig
from updates2mqtt.helpers import Throttler
from updates2mqtt.integrations.docker import DockerProvider
from updates2mqtt.integrations.docker_enrich import (
    REGISTRIES,
    ContainerDistributionAPIVersionLookup,
    DockerImageInfo,
    fetch_url,
)
from updates2mqtt.model import Discovery

if TYPE_CHECKING:
    from httpx import Response

log = structlog.get_logger()


"""
Super simple CLI

Command can be `container`,`tags`,`manifest` or `blob`

* `container=container-name`
* `container=hash`
* `dump=csv`
* `tags=ghcr.io/
* `blob=mcr.microsoft.com/dotnet/sdk:latest`
* `tags=quay.io/linuxserver.io/babybuddy`
* `blob=ghcr.io/blakeblackshear/frigate@sha256:759c36ee869e3e60258350a2e221eae1a4ba1018613e0334f1bc84eb09c4bbbc`

In addition, a `log_level=DEBUG` or other level can be added, `github_token` to try a personal access
token for GitHub release info retrieval, or `api=docker_client` to use the older API (defaults to `api=OCI_V2`)


"""

OCI_MANIFEST_TYPES: list[str] = [
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.oci.descriptor.v1+json",
    "application/vnd.oci.empty.v1+json",
]

OCI_CONFIG_TYPES: list[str] = [
    "application/vnd.oci.image.config.v1+json",
]

OCI_LAYER_TYPES: list[str] = [
    "application/vnd.oci.image.layer.v1.tar",
    "application/vnd.oci.image.layer.v1.tar+gzip",
    "application/vnd.oci.image.layer.v1.tar+zstd",
]

OCI_NONDISTRIBUTABLE_LAYER_TYPES: list[str] = [
    "application/vnd.oci.image.layer.nondistributable.v1.tar",
    "application/vnd.oci.image.layer.nondistributable.v1.tar+gzip",
    "application/vnd.oci.image.layer.nondistributable.v1.tar+zstd",
]

# Docker Compatibility MIME Types
DOCKER_MANIFEST_TYPES: list[str] = [
    "application/vnd.docker.distribution.manifest.v2+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
    "application/vnd.docker.distribution.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.v1+prettyjws",
]

DOCKER_CONFIG_TYPES: list[str] = [
    "application/vnd.docker.container.image.v1+json",
]

DOCKER_LAYER_TYPES: list[str] = [
    "application/vnd.docker.image.rootfs.diff.tar.gzip",
    "application/vnd.docker.image.rootfs.foreign.diff.tar.gzip",
]

# Combined constants
ALL_MANIFEST_TYPES: list[str] = OCI_MANIFEST_TYPES + DOCKER_MANIFEST_TYPES
ALL_CONFIG_TYPES: list[str] = OCI_CONFIG_TYPES + DOCKER_CONFIG_TYPES
ALL_LAYER_TYPES: list[str] = OCI_LAYER_TYPES + OCI_NONDISTRIBUTABLE_LAYER_TYPES + DOCKER_LAYER_TYPES

# All content types that might be returned by the API
ALL_OCI_MEDIA_TYPES: list[str] = (
    ALL_MANIFEST_TYPES
    + ALL_CONFIG_TYPES
    + ALL_LAYER_TYPES
    + ["application/octet-stream", "application/json"]  # Error responses
)


def dump_url(doc_type: str, img_ref: str, cli_conf: DictConfig) -> None:
    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(cli_conf.get("log_level", "ERROR")))

    lookup = ContainerDistributionAPIVersionLookup(Throttler(), RegistryConfig())
    img_info = DockerImageInfo(img_ref)
    if not img_info.index_name or not img_info.name:
        log.error("Unable to parse %ss", img_ref)
        return

    api_host: str | None = REGISTRIES.get(img_info.index_name, (img_info.index_name, img_info.index_name))[1]

    if doc_type == "blob":
        if not img_info.pinned_digest:
            log.warning("No digest found in %s", img_ref)
            return
        url: str = f"https://{api_host}/v2/{img_info.name}/blobs/{img_info.pinned_digest}"
    elif doc_type == "manifest":
        if not img_info.tag_or_digest:
            log.warning("No tag or digest found in %s", img_ref)
            return
        url = f"https://{api_host}/v2/{img_info.name}/manifests/{img_info.tag_or_digest}"
    elif doc_type == "tags":
        url = f"https://{api_host}/v2/{img_info.name}/tags/list"
    else:
        return

    token: str | None = lookup.fetch_token(img_info.index_name, img_info.name)

    response: Response | None = fetch_url(url, bearer_token=token, follow_redirects=True, response_type=ALL_OCI_MEDIA_TYPES)
    if response and response.is_error:
        log.warning(f"{response.status_code}: {url}")
        log.warning(response.text)
    elif response and response.is_success:
        log.debug(f"{response.status_code}: {url}")
        log.debug("HEADERS")
        for k, v in response.headers.items():
            log.debug(f"{k}: {v}")
        log.debug("CONTENTS")

        print_json(response.text)


def docker_provider(cli_conf: DictConfig) -> DockerProvider:
    docker_scanner = DockerProvider(
        DockerConfig(registry=RegistryConfig(api=cli_conf.get("api", "OCI_V2"))),
        NodeConfig(),
        packages={},
        github_cfg=GitHubConfig(access_token=cli_conf.get("github_token")),
        self_bounce=None,
    )
    docker_scanner.initialize()
    return docker_scanner


async def dump(fmt: str, cli_conf: DictConfig) -> None:
    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(cli_conf.get("log_level", "ERROR")))
    console = Console()
    docker_scanner: DockerProvider = docker_provider(cli_conf)
    if fmt == "csv":
        console.print(
            ",".join(
                f'"{v}"'
                for v in (
                    "name",
                    "ref",
                    "registry",
                    "installed_version",
                    "latest_version",
                    "version_basis",
                    "title",
                    "can_update",
                    "can_build",
                    "can_restart",
                    "update_type",
                    "source",
                    "throttled",
                )
            ),
            style="bold white on black",
        )
        async for discovery in docker_scanner.scan("cli", False):
            v = discovery.as_dict()
            console.print(
                ",".join(
                    f'"{v}"'
                    for v in (
                        v["name"],
                        v["current_detail"].get("image_ref"),  # type: ignore[union-attr]
                        v["current_detail"].get("index_name"),  # type: ignore[union-attr]
                        v["installed_version"],
                        v["latest_version"],
                        v["version_basis"],
                        v["title"],
                        v["can_update"],
                        v["can_build"],
                        v["can_restart"],
                        v["update_type"],
                        v.get("release", {}).get("source"),  # type: ignore[union-attr]
                        v.get("last_scan", {}).get("throttled"),  # type: ignore[union-attr]
                    )
                )
            )
    else:
        log.warning(f"Unsupported dump format {fmt}")


def main() -> None:
    # will be a proper cli someday
    cli_conf: DictConfig = OmegaConf.from_cli()

    if cli_conf.get("blob"):
        dump_url("blob", cli_conf.get("blob"), cli_conf)
    elif cli_conf.get("manifest"):
        dump_url("manifest", cli_conf.get("manifest"), cli_conf)
    elif cli_conf.get("tags"):
        dump_url("tags", cli_conf.get("tags"), cli_conf)
    elif cli_conf.get("dump"):
        import asyncio

        asyncio.run(dump(cli_conf.get("dump"), cli_conf))

    else:
        structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(cli_conf.get("log_level", "INFO")))

        docker_scanner = docker_provider(cli_conf)
        discovery: Discovery | None = docker_scanner.rescan(
            Discovery(docker_scanner, cli_conf.get("container", "frigate"), "cli", "manual")
        )
        if discovery:
            log.info(discovery.as_dict())


if __name__ == "__main__":
    main()
