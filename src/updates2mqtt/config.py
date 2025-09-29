import os
import typing
from dataclasses import dataclass, field
from pathlib import Path

import structlog
from omegaconf import MISSING, MissingMandatoryValue, OmegaConf, ValidationError

log = structlog.get_logger()


@dataclass
class MqttConfig:
    host: str = "localhost"
    user: str = MISSING
    password: str = MISSING
    port: int = 1883
    topic_root: str = "updates2mqtt"


@dataclass
class MetadataSourceConfig:
    enabled: bool = True


@dataclass
class DockerConfig:
    enabled: bool = True
    allow_pull: bool = True
    allow_restart: bool = True
    allow_build: bool = True
    compose_version: str = "v2"
    default_entity_picture_url: str = "https://www.docker.com/wp-content/uploads/2022/03/Moby-logo.png"
    device_icon: str = "mdi:train-car-container"
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


@dataclass
class NodeConfig:
    name: str = "UNKNOWN"


@dataclass
class LogConfig:
    level: str = "INFO"


@dataclass
class Config:
    log: LogConfig = field(default_factory=LogConfig)
    node: NodeConfig = field(default_factory=NodeConfig)
    mqtt: MqttConfig = field(default_factory=MqttConfig)
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


def load_package_info(pkginfo_file_path: Path) -> UpdateInfoConfig:
    if pkginfo_file_path.exists():
        log.debug("Loading common package update info", path=pkginfo_file_path)
        cfg = OmegaConf.load(pkginfo_file_path)
    else:
        log.warn("No common package update info found", path=pkginfo_file_path)
        cfg = OmegaConf.structured(UpdateInfoConfig)
    OmegaConf.set_readonly(cfg, True)
    return typing.cast("UpdateInfoConfig", cfg)


def load_app_config(conf_file_path: Path) -> Config | None:
    base_cfg = OmegaConf.structured(Config)
    if conf_file_path.exists():
        cfg = OmegaConf.merge(base_cfg, OmegaConf.load(conf_file_path))
    else:
        try:
            log.debug("Creating config directory if not already present", path=conf_file_path)
            conf_file_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            log.exception("Unable to create config directory", path=conf_file_path.parent)
        try:
            conf_file_path.write_text(OmegaConf.to_yaml(base_cfg))
        except Exception:
            log.exception("Unable to write config file", path=conf_file_path)
        cfg = base_cfg

    if cfg.node.name is None:
        cfg.node.name = os.uname().nodename

    try:
        # Validate that all required fields are present, throw exception now rather than when config first used
        OmegaConf.to_container(cfg, throw_on_missing=True)
        OmegaConf.set_readonly(cfg, True)
        return typing.cast("Config", cfg)
    except (MissingMandatoryValue, ValidationError) as e:
        log.error("Configuration error: %s", e, path=conf_file_path)
        return None
