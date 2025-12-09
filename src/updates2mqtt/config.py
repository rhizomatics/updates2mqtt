import os
import typing
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

import structlog
from omegaconf import MISSING, DictConfig, MissingMandatoryValue, OmegaConf, ValidationError

log = structlog.get_logger()


class LogLevel(StrEnum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


@dataclass
class MqttConfig:
    host: str = "${oc.env:MQTT_HOST,localhost}"
    user: str = f"${{oc.env:MQTT_USER,{MISSING}}}"
    password: str = f"${{oc.env:MQTT_PASS,{MISSING}}}"
    port: int = "${oc.decode:${oc.env:MQTT_PORT,1883}}"  # type: ignore[assignment]
    topic_root: str = "updates2mqtt"
    protocol: str = "${oc.env:MQTT_VERSION,3.11}"


@dataclass
class MetadataSourceConfig:
    enabled: bool = True
    cache_ttl: int = 60 * 60 * 24 * 7  # 1 week


@dataclass
class DockerConfig:
    enabled: bool = True
    allow_pull: bool = True
    allow_restart: bool = True
    allow_build: bool = True
    compose_version: str = "v2"
    default_entity_picture_url: str = "https://www.docker.com/wp-content/uploads/2022/03/Moby-logo.png"
    # Icon to show when browsing entities in Home Assistant
    device_icon: str = "mdi:docker"
    discover_metadata: dict[str, MetadataSourceConfig] = field(
        default_factory=lambda: {"linuxserver.io": MetadataSourceConfig(enabled=True)}
    )


@dataclass
class HomeAssistantDiscoveryConfig:
    prefix: str = "homeassistant"
    enabled: bool = True


@dataclass
class HomeAssistantConfig:
    discovery: HomeAssistantDiscoveryConfig = field(default_factory=HomeAssistantDiscoveryConfig)
    state_topic_suffix: str = "state"
    device_creation: bool = True
    force_command_topic: bool = False
    area: str | None = None


@dataclass
class HealthCheckConfig:
    enabled: bool = True
    interval: int = 300  # Interval in seconds to publish healthcheck message, 0 to disable
    topic_template: str = "healthcheck/{node_name}/updates2mqtt"


@dataclass
class NodeConfig:
    name: str = field(default_factory=lambda: os.uname().nodename.replace(".local", ""))
    git_path: str = "/usr/bin/git"
    healthcheck: HealthCheckConfig = field(default_factory=HealthCheckConfig)


@dataclass
class LogConfig:
    level: LogLevel = "${oc.decode:${oc.env:U2M_LOG_LEVEL,INFO}}"  # type: ignore[assignment] # pyright: ignore[reportAssignmentType]


@dataclass
class Config:
    log: LogConfig = field(default_factory=LogConfig)  # pyright: ignore[reportArgumentType, reportCallIssue]
    node: NodeConfig = field(default_factory=NodeConfig)
    mqtt: MqttConfig = field(default_factory=MqttConfig)  # pyright: ignore[reportArgumentType, reportCallIssue]
    homeassistant: HomeAssistantConfig = field(default_factory=HomeAssistantConfig)
    docker: DockerConfig = field(default_factory=DockerConfig)
    scan_interval: int = 60 * 60 * 3


@dataclass
class DockerPackageUpdateInfo:
    image_name: str = MISSING


@dataclass
class PackageUpdateInfo:
    docker: DockerPackageUpdateInfo | None = field(default_factory=DockerPackageUpdateInfo)
    logo_url: str | None = None
    release_notes_url: str | None = None


@dataclass
class UpdateInfoConfig:
    common_packages: dict[str, PackageUpdateInfo] = field(default_factory=lambda: {})


class IncompleteConfigException(BaseException):
    pass


def load_package_info(pkginfo_file_path: Path) -> dict[str, PackageUpdateInfo]:
    if pkginfo_file_path.exists():
        log.debug("Loading common package update info", path=pkginfo_file_path)
        cfg = OmegaConf.load(pkginfo_file_path)
    else:
        log.warn("No common package update info found", path=pkginfo_file_path)
        cfg = OmegaConf.structured(UpdateInfoConfig)
    try:
        # omegaconf broken-ness on optional fields and converting to backclasses
        pkg_conf: dict[str, PackageUpdateInfo] = {
            pkg: PackageUpdateInfo(**pkg_cfg) for pkg, pkg_cfg in cfg.common_packages.items()
        }
        return pkg_conf
    except (MissingMandatoryValue, ValidationError) as e:
        log.error("Configuration error %s", e, path=pkginfo_file_path.as_posix())
        raise


def is_autogen_config() -> bool:
    env_var: str | None = os.environ.get("U2M_AUTOGEN_CONFIG")
    return not (env_var and env_var.lower() in ("no", "0", "false"))


def load_app_config(conf_file_path: Path, return_invalid: bool = False) -> Config | None:
    base_cfg: DictConfig = OmegaConf.structured(Config)
    if conf_file_path.exists():
        cfg: DictConfig = typing.cast("DictConfig", OmegaConf.merge(base_cfg, OmegaConf.load(conf_file_path)))
    elif is_autogen_config():
        if not conf_file_path.parent.exists():
            try:
                log.debug(f"Creating config directory {conf_file_path.parent} if not already present")
                conf_file_path.parent.mkdir(parents=True, exist_ok=True)
            except Exception:
                log.warning("Unable to create config directory", path=conf_file_path.parent)
        try:
            conf_file_path.write_text(OmegaConf.to_yaml(base_cfg))
            log.info(f"Auto-generated a new config file at {conf_file_path}")
        except Exception:
            log.warning("Unable to write config file", path=conf_file_path)
        cfg = base_cfg
    else:
        cfg = base_cfg

    try:
        # Validate that all required fields are present, throw exception now rather than when config first used
        OmegaConf.to_container(cfg, throw_on_missing=True)
        OmegaConf.set_readonly(cfg, True)
        config: Config = typing.cast("Config", cfg)

        if config.mqtt.user in ("", MISSING) or config.mqtt.password in ("", MISSING):
            log.info("The config has place holders for MQTT user and/or password")
            if not return_invalid:
                return None
        return config
    except (MissingMandatoryValue, ValidationError) as e:
        log.error("Configuration error %s", e, path=conf_file_path.as_posix())
        if return_invalid and cfg is not None:
            return typing.cast("Config", cfg)
        raise
