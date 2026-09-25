import asyncio
import json
import re
import ssl
import sys
import typing
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import TYPE_CHECKING

import structlog
from docker.errors import DockerException
from omegaconf import MISSING, DictConfig, MissingMandatoryValue, OmegaConf, ValidationError
from rich import print_json
from rich.console import Console

from updates2mqtt.app import CONF_FILE
from updates2mqtt.config import (
    DockerConfig,
    GitHubConfig,
    HomeAssistantConfig,
    MqttConfig,
    NodeConfig,
    RegistryAPI,
    RegistryConfig,
    TlsMode,
)
from updates2mqtt.helpers import Throttler
from updates2mqtt.integrations.docker import DockerProvider
from updates2mqtt.integrations.docker_enrich import (
    REGISTRIES,
    ContainerDistributionAPIVersionLookup,
    DockerImageInfo,
    fetch_url,
)
from updates2mqtt.model import Discovery
from updates2mqtt.mqtt import MqttPublisher

if TYPE_CHECKING:
    from httpx import Response

log = structlog.get_logger()


HELP = """
Super simple CLI

Command can be `container`,`dump`,`tags`,`manifest`,`blob` or `mqtt`

* `container=container-name`
* `container=hash`
* `dump=csv`
* `dump=json`
* `dump=json container=frigate`
* `tags=ghcr.io/
* `blob=mcr.microsoft.com/dotnet/sdk:latest`
* `tags=quay.io/linuxserver.io/babybuddy`
* `blob=ghcr.io/blakeblackshear/frigate@sha256:759c36ee869e3e60258350a2e221eae1a4ba1018613e0334f1bc84eb09c4bbbc`
* `mqtt=check` to show MQTT settings and test the broker connection, optionally with `config=path/to/config.yaml`

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
        DockerConfig(registry=RegistryConfig(api=RegistryAPI[str(cli_conf.get("api", "OCI_V2"))])),
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
    if cli_conf.get("container"):

        async def single_discovery() -> AsyncGenerator[Discovery]:
            result = docker_scanner.rescan(Discovery(docker_scanner, cli_conf["container"], "cli", "manual"))
            if result:
                yield result

        source: AsyncGenerator[Discovery] = single_discovery()
    else:
        source = docker_scanner.scan("cli", False)

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
        async for discovery in source:
            v = discovery.as_dict()
            console.print(
                ",".join(
                    f'"{v}"'
                    for v in (
                        v["name"],
                        v["current_detail"].get("image_ref"),  # type: ignore[union-attr] #ty: ignore[unresolved-attribute]
                        v["current_detail"].get("index_name"),  # type: ignore[union-attr] #ty: ignore[unresolved-attribute]
                        v["installed_version"],
                        v["latest_version"],
                        v["version_basis"],
                        v["title"],
                        v["can_update"],
                        v["can_build"],
                        v["can_restart"],
                        v["update_type"],
                        v.get("release", {}).get("source"),  # type: ignore[union-attr] #ty: ignore[unresolved-attribute]
                        v.get("last_scan", {}).get("throttled"),  # type: ignore[union-attr] #ty: ignore[unresolved-attribute]
                    )
                )
            )
    elif fmt == "json":
        print_json(json.dumps([v.as_dict() async for v in source]))
    else:
        log.warning(f"Unsupported dump format {fmt}")


MQTT_SECRETS: tuple[str, ...] = ("password", "client_key_password")
MQTT_FILES: tuple[str, ...] = ("ca_certs", "client_cert", "client_key")


def load_mqtt_config(conf_file_path: Path) -> DictConfig:
    mqtt_cfg: DictConfig = OmegaConf.structured(MqttConfig)
    if conf_file_path.exists():
        log.info(f"Using MQTT settings from {conf_file_path} and environment")
        file_cfg = OmegaConf.load(conf_file_path)
        if isinstance(file_cfg, DictConfig) and file_cfg.get("mqtt"):
            mqtt_cfg = typing.cast("DictConfig", OmegaConf.merge(mqtt_cfg, file_cfg.mqtt))
    else:
        log.info(f"No config file at {conf_file_path}, using environment and defaults only")
    return mqtt_cfg


def check_mqtt(cli_conf: DictConfig) -> bool:
    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(cli_conf.get("log_level", "INFO")))
    mqtt_cfg: DictConfig = load_mqtt_config(Path(cli_conf.get("config", CONF_FILE)))
    raw: dict[str, typing.Any] = typing.cast("dict[str, typing.Any]", OmegaConf.to_container(mqtt_cfg, resolve=False))

    valid = True
    for key, raw_value in raw.items():
        env_match = re.search(r"oc\.env:(\w+)", str(raw_value))
        source: str = f" (env {env_match.group(1)})" if env_match else ""
        try:
            value = mqtt_cfg[key]
        except (MissingMandatoryValue, ValidationError) as e:
            log.error(f"{key}{source}: invalid or missing - {e}")
            valid = False
            continue
        if value == MISSING:
            log.error(f"{key}{source}: required but not set")
            valid = False
            continue
        if key in MQTT_FILES and value and not Path(value).is_file():
            log.error(f"{key}{source}: file not found at {value}")
            valid = False
            continue
        if key in MQTT_SECRETS:
            display = "<set>" if value else "<not set>"
        elif isinstance(value, int) and key == "cert_reqs":
            display = ssl.VerifyMode(value).name
        else:
            display = value if value not in (None, "") else "<not set>"
        log.info(f"{key}{source}: {display}")

    if not valid:
        log.error("MQTT configuration is invalid, not attempting broker connection")
        return False
    cfg: MqttConfig = typing.cast("MqttConfig", mqtt_cfg)
    if cfg.tls_mode == TlsMode.OFF and cfg.port == 8883:
        log.warning("Port 8883 is normally used for TLS, but tls_mode is off")

    # separate client id so a running updates2mqtt instance isn't disconnected by the broker
    publisher = MqttPublisher(cfg, NodeConfig(name=f"{NodeConfig().name}-cli-check"), HomeAssistantConfig())
    log.info(f"Connecting to {cfg.host}:{cfg.port} as {cfg.user}, timeout {cfg.connect_timeout}s")
    try:
        publisher.start(asyncio.new_event_loop())
    except OSError as e:
        log.error(f"Broker connection failed: {e}")
        return False
    try:
        if publisher.connected.is_set():
            log.info(f"Broker connection to {cfg.host}:{cfg.port} succeeded")
            return True
        if publisher.fatal_failure.is_set():
            log.error("Broker rejected credentials")
        else:
            log.error(f"No successful broker connection within {cfg.connect_timeout}s")
        return False
    finally:
        publisher.stop()


def main() -> None:
    # will be a proper cli someday
    cli_conf: DictConfig = OmegaConf.from_cli()

    try:
        run_command(cli_conf)
    except DockerException as e:
        log.error(f"Unable to connect to Docker, check it is running and accessible: {e}")
        sys.exit(1)


def run_command(cli_conf: DictConfig) -> None:
    if "help" in cli_conf or "--help" in cli_conf:
        log.info(HELP)
    elif cli_conf.get("blob"):
        dump_url("blob", cli_conf.get("blob"), cli_conf)
    elif cli_conf.get("manifest"):
        dump_url("manifest", cli_conf.get("manifest"), cli_conf)
    elif cli_conf.get("tags"):
        dump_url("tags", cli_conf.get("tags"), cli_conf)
    elif cli_conf.get("mqtt"):
        if not check_mqtt(cli_conf):
            sys.exit(1)
    elif cli_conf.get("dump"):
        asyncio.run(dump(cli_conf.get("dump"), cli_conf))
    elif cli_conf.get("container"):
        structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(cli_conf.get("log_level", "INFO")))

        docker_scanner = docker_provider(cli_conf)
        discovery: Discovery | None = docker_scanner.rescan(
            Discovery(docker_scanner, cli_conf.get("container"), "cli", "manual")
        )
        if discovery:
            log.info(discovery.as_dict())
    else:
        log.info(HELP)


if __name__ == "__main__":
    main()
