from typing import TYPE_CHECKING

import structlog
from omegaconf import DictConfig, OmegaConf
from rich import print_json

from updates2mqtt.config import DockerConfig, NodeConfig, RegistryConfig
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

python updates2mqtt.cli container=frigate

python updates2mqtt.cli container=frigate api=docker_client log_level=DEBUG

ython3 updates2mqtt/cli.py blob=ghcr.io/homarr-labs/homarr@sha256:af79a3339de5ed8ef7f5a0186ff3deb86f40b213ba75249291f2f68aef082a25 | jq '.config.Labels'

python3 updates2mqtt/cli.py manifest=ghcr.io/blakeblackshear/frigate:stable

python3 updates2mqtt/cli.py blob=ghcr.io/blakeblackshear/frigate@sha256:ef8d56a7d50b545af176e950ce328aec7f0b7bc5baebdca189fe661d97924980

python3 updates2mqtt/cli.py manifest=ghcr.io/blakeblackshear/frigate@sha256:c68fd78fd3237c9ba81b5aa927f17b54f46705990f43b4b5d5596cfbbb626af4
"""  # noqa: E501

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
    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(cli_conf.get("log_level", "WARNING")))

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
    else:
        return

    token: str | None = lookup.fetch_token(img_info.index_name, img_info.name)

    response: Response | None = fetch_url(url, bearer_token=token, follow_redirects=True, response_type=ALL_OCI_MEDIA_TYPES)
    if response:
        log.debug(f"{response.status_code}: {url}")
        log.debug("HEADERS")
        for k, v in response.headers.items():
            log.debug(f"{k}: {v}")
        log.debug("CONTENTS")
        print_json(response.text)


def main() -> None:
    # will be a proper cli someday
    cli_conf: DictConfig = OmegaConf.from_cli()

    if cli_conf.get("blob"):
        dump_url("blob", cli_conf.get("blob"), cli_conf)
    elif cli_conf.get("manifest"):
        dump_url("manifest", cli_conf.get("manifest"), cli_conf)
    else:
        structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(cli_conf.get("log_level", "INFO")))

        docker_scanner = DockerProvider(
            DockerConfig(registry=RegistryConfig(api=cli_conf.get("api", "OCI_V2"))), NodeConfig(), None
        )
        docker_scanner.initialize()
        discovery: Discovery | None = docker_scanner.rescan(
            Discovery(docker_scanner, cli_conf.get("container", "frigate"), "cli", "manual")
        )
        if discovery:
            log.info(discovery.as_dict())


if __name__ == "__main__":
    main()
