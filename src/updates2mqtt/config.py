import os
import ssl
import tempfile
import typing
from dataclasses import dataclass, field
from enum import EnumMeta, StrEnum, auto
from pathlib import Path
from typing import Any

import structlog
from omegaconf import MISSING, DictConfig, MissingMandatoryValue, OmegaConf, ValidationError

log = structlog.get_logger()

type StrKeyedDict = dict[str, str | list[Any] | dict[str, Any] | bool | int | None]

PKG_INFO_FILE = Path("./common_packages.yaml")
UNKNOWN_VERSION = "UNKNOWN"
VERSION_RE = r"[vVr]?[0-9]+(\.[0-9]+)*"
# source: https://semver.org/#is-there-a-suggested-regular-expression-regex-to-check-a-semver-string
SEMVER_RE = r"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)(?:-(?P<prerelease>(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?(?:\+(?P<buildmetadata>[0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$"

SOURCE_PLATFORM_GITHUB = "GitHub"
SOURCE_PLATFORM_CODEBERG = "CodeBerg"
SOURCE_PLATFORM_GITLAB = "GitLab"
SOURCE_PLATFORM_SOURCEHUT = "SourceHut"
SOURCE_PLATFORMS: dict[str, str] = {
    SOURCE_PLATFORM_GITHUB: r"https://github\.com/.*",
    SOURCE_PLATFORM_GITLAB: r"https://gitlab\.com/.*",
    SOURCE_PLATFORM_CODEBERG: r"https://codeberg\.org/.*",
    SOURCE_PLATFORM_SOURCEHUT: r"https://sr\.ht/.*",
}


class UpdatePolicy(StrEnum):
    AUTO = "Auto"
    PASSIVE = "Passive"


class PublishPolicy(StrEnum):
    HOMEASSISTANT = "HomeAssistant"
    MQTT = "MQTT"
    SILENT = "Silent"


class CaseInsensitiveEnumMeta(EnumMeta):
    def __getitem__(self, name: str) -> Any:
        return self._member_map_[name] if name in self._member_map_ else self._member_map_[name.upper()]


class LogLevel(StrEnum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class RegistryAPI(StrEnum, metaclass=CaseInsensitiveEnumMeta):
    """How the latest version of an image is looked up, matched case insensitively"""

    OCI_V2 = "OCI_V2"
    """Built-in OCI Distribution v2 client, with manifests, configs and annotations, see RFC 0001"""
    OCI_V2_MINIMAL = "OCI_V2_MINIMAL"
    """Built-in OCI v2 client, using the manifest only, without fetching the image config for labels"""
    DOCKER_CLIENT = "DOCKER_CLIENT"
    """The Docker engine's own distribution API"""
    DISABLED = "DISABLED"
    """No registry lookups"""


class VersionType:
    SHORT_SHA = "short_sha"
    FULL_SHA = "full_sha"
    VERSION_REVISION = "version_revision"
    VERSION = "version"


@dataclass
class RegistryConfig:
    """Container registry lookups, the `docker.registry` block"""

    api: RegistryAPI = RegistryAPI.OCI_V2
    """Registry client used to find the latest image"""
    mutable_cache_ttl: int | None = 60 * 60
    """Seconds to cache responses that can change, such as tag lookups"""
    immutable_cache_ttl: int | None = 7776000
    """Seconds to cache responses addressed by digest, which can't change"""
    token_cache_ttl: int | None = None
    """Seconds to cache registry auth tokens, or `None` to follow the registry's own expiry"""


class TlsMode(StrEnum, metaclass=CaseInsensitiveEnumMeta):
    """MQTT broker TLS, matched case insensitively"""

    ON = auto()
    """TLS with certificate verification"""
    OFF = auto()
    """Plain TCP"""
    INSECURE = auto()
    """TLS without verifying the broker's certificate or host name"""


@dataclass
class MqttConfig:
    """MQTT broker connection, the `mqtt` block"""

    host: str = "${oc.env:MQTT_HOST,localhost}"
    """Broker host name or IP address, from `MQTT_HOST`"""
    user: str = f"${{oc.env:MQTT_USER,{MISSING}}}"
    """Broker user name, from `MQTT_USER`, the one mandatory setting"""
    password: str | None = "${oc.env:MQTT_PASS,''}"
    """Broker password, from `MQTT_PASS`"""
    port: int = "${oc.decode:${oc.env:MQTT_PORT,1883}}"  # type: ignore[assignment] # ty: ignore[invalid-assignment]
    """Broker port, from `MQTT_PORT`"""
    topic_root: str = "updates2mqtt"
    """First level of every topic Updates2MQTT publishes, other than Home Assistant discovery and healthcheck"""
    protocol: str = "${oc.env:MQTT_VERSION,3.11}"
    """MQTT protocol version, `3.1`, `3.11` or `5`, from `MQTT_VERSION`"""
    transport: str = "${oc.env:MQTT_TRANSPORT,'tcp'}"
    """`tcp`, `websockets` or `unix`, from `MQTT_TRANSPORT`"""
    connect_timeout: float = 20
    """Seconds to wait for the broker to accept a connection"""
    keepalive: int = 30
    """Seconds between MQTT keepalive pings"""
    tls_mode: TlsMode = "${oc.env:MQTT_TLS_MODE,off}"  # type: ignore[assignment] # ty: ignore[invalid-assignment]
    """TLS for the broker connection, from `MQTT_TLS_MODE`"""
    ca_certs: str | None = "${oc.env:MQTT_CA_CERTS,''}"
    """CA certificate bundle file to verify the broker, from `MQTT_CA_CERTS`"""
    client_cert: str | None = "${oc.env:MQTT_CLIENT_CERT,''}"
    """Client certificate file for mutual TLS, from `MQTT_CLIENT_CERT`"""
    client_key: str | None = "${oc.env:MQTT_CLIENT_KEY,''}"
    """Client private key file for mutual TLS, from `MQTT_CLIENT_KEY`"""
    client_key_password: str | None = "${oc.env:MQTT_CLIENT_KEY_PASS,''}"
    """Password for the client private key, from `MQTT_CLIENT_KEY_PASS`"""
    cert_reqs: ssl.VerifyMode = "${oc.env:MQTT_CERT_REQUIRED,CERT_REQUIRED}"  # type: ignore[assignment] # ty: ignore[invalid-assignment]
    """Broker certificate verification, `CERT_REQUIRED`, `CERT_OPTIONAL` or `CERT_NONE`, from `MQTT_CERT_REQUIRED`"""


@dataclass
class GitHubConfig:
    """GitHub API access for release notes, the `github` block"""

    access_token: str | None = None
    """Personal access token, to raise the GitHub API rate limit"""
    mutable_cache_ttl: int = 60 * 60 * 15
    """Seconds to cache GitHub release lookups"""


@dataclass
class MetadataSourceConfig:
    """A catalogue of image metadata, such as linuxserver.io, in `docker.discover_metadata`"""

    enabled: bool = True
    """Look up logos, release notes and source links in this catalogue"""
    cache_ttl: int = 60 * 60 * 24 * 7
    """Seconds to cache the catalogue"""


@dataclass
class Selector:
    """Regular expression filter, where a value is selected if it matches an `include` and no `exclude`"""

    include: list[str] | None = None
    """Patterns to select, or all if empty"""
    exclude: list[str] | None = None
    """Patterns to reject, applied after `include`"""


class VersionPolicy(StrEnum):
    """How the installed and latest versions are described"""

    AUTO = "AUTO"
    """Pick the best available for the image"""
    VERSION = "VERSION"
    """Version label or tag only"""
    DIGEST = "DIGEST"
    """Image digest only"""
    VERSION_DIGEST = "VERSION_DIGEST"
    """Version with an abbreviated digest"""
    TIMESTAMP = "TIMESTAMP"
    """Image creation time"""


@dataclass
class DockerPackageUpdateInfo:
    """Docker specifics of a package"""

    image_name: typing.Any = MISSING
    """Untagged image ref, either a single string or a list of strings, mandatory"""
    version_policy: VersionPolicy = VersionPolicy.AUTO
    """Version policy for images of this package"""


def docker_image_names(docker_info: DockerPackageUpdateInfo) -> list[str]:
    if isinstance(docker_info.image_name, str):
        return [docker_info.image_name]
    return list(docker_info.image_name)


@dataclass
class PackageUpdateInfo:
    """Metadata for a package, an entry in `packages`, or in the built-in common packages"""

    docker: DockerPackageUpdateInfo | None = field(default_factory=DockerPackageUpdateInfo)
    """Images that belong to this package"""
    logo_url: str | None = None
    """Picture shown on the Home Assistant update entity"""
    release_notes_url: str | None = None
    """Link to the release notes"""
    source_repo_url: str | None = None
    """Source code repository, used to find release notes on GitHub"""


@dataclass
class PortainerConfig:
    """Portainer API access, used to redeploy stacks whose compose files live in Portainer's data volume"""

    url: str | None = "${oc.env:PORTAINER_URL,null}"
    """Portainer base URL, from `PORTAINER_URL`"""
    api_key: str | None = "${oc.env:PORTAINER_API_KEY,null}"
    """Portainer API access token, from `PORTAINER_API_KEY`"""
    verify_ssl: bool = "${oc.env:PORTAINER_VERIFY_SSL,true}"  # type: ignore[assignment] # ty: ignore[invalid-assignment]
    """Verify Portainer's TLS certificate, from `PORTAINER_VERIFY_SSL`"""
    ca_certs: str | None = "${oc.env:PORTAINER_CA_CERTS,null}"
    """CA certificate bundle to verify Portainer, e.g. a private root CA, from `PORTAINER_CA_CERTS`"""
    timeout: int = 300
    """Seconds allowed for API calls, and for a stack deployment to finish"""


@dataclass
class DockerConfig:
    """Docker container scanning and updating, the `docker` block"""

    enabled: bool = True
    """Scan Docker containers"""
    allow_pull: bool = True
    """Allow updates by pulling the new image"""
    allow_restart: bool = True
    """Allow updates to recreate the container with `docker compose up`"""
    allow_build: bool = True
    """Allow updates of local builds with `docker compose build`"""
    git_repo_roots: list[str] = field(default_factory=list)
    """Directories that local build git repos have to be inside, e.g. `["/home/containers"]`.
    Any path set on a container is accepted while this is empty"""
    trust_image_settings: list[str] = field(default_factory=list)
    """Images trusted to supply any setting through their own labels or env, e.g. ones you build yourself.
    Plain image refs only, as written in the compose file, with or without a tag, e.g. `["ghcr.io/me/myapp"]`.
    Wildcards and patterns are refused"""
    remove_old_image: bool = "${oc.env:U2M_REMOVE_OLD_IMAGE,false}"  # type: ignore[assignment] # ty: ignore[invalid-assignment]
    """Remove the previous image once a container has been recreated with the new one, from `U2M_REMOVE_OLD_IMAGE`"""
    compose_version: str = "v2"
    """`v2` for `docker compose`, `v1` for `docker-compose`"""
    max_concurrent_updates: int = "${oc.env:U2M_MAX_CONCURRENT_UPDATES,3}"  # type: ignore[assignment] # ty: ignore[invalid-assignment]
    """Updates run in parallel up to this limit, further ones queue for a free slot, from `U2M_MAX_CONCURRENT_UPDATES`"""
    default_entity_picture_url: str = "https://www.docker.com/wp-content/uploads/2022/03/Moby-logo.png"
    """Picture for update entities with no package logo"""
    device_icon: str = "mdi:docker"
    """Icon to show when browsing entities in Home Assistant"""
    discover_metadata: dict[str, MetadataSourceConfig] = field(
        default_factory=lambda: {
            "linuxserver.io": MetadataSourceConfig(enabled=True),
            "hotio.dev": MetadataSourceConfig(enabled=True),
        }
    )
    """Online catalogues of image metadata, keyed by name"""
    registry: RegistryConfig = field(default_factory=lambda: RegistryConfig())
    """Registry client and caching"""
    default_api_backoff: int = 60 * 15
    """Seconds to back off a registry API after it throttles"""
    image_ref_select: Selector = field(default_factory=lambda: Selector())
    """Image refs to publish"""
    version_select: Selector = field(default_factory=lambda: Selector())
    """Latest versions to publish"""
    version_policy: VersionPolicy = VersionPolicy.AUTO
    """Default version policy for all containers"""
    registry_select: Selector = field(default_factory=lambda: Selector())
    """Registries, by index name, to look up latest versions in"""
    container_select: Selector = field(default_factory=lambda: Selector())
    """Container names to ignore completely, e.g. exclude `["^lab_", "^beta_"]`, as regular expressions"""
    portainer: PortainerConfig = field(default_factory=lambda: PortainerConfig())
    """Portainer API access, for stacks managed by Portainer"""
    cooldown: str = "3d"
    """How long a release has to be known before it's eligible to update, e.g. `72h`, `3d`, `1w`, or `0` for none.
    Observe only for now, reported in the update attributes, see RFC 0002"""


@dataclass
class HomeAssistantDiscoveryConfig:
    """Home Assistant MQTT discovery, the `homeassistant.discovery` block"""

    prefix: str = "homeassistant"
    """Discovery topic prefix, matching Home Assistant's MQTT integration setting"""
    enabled: bool = True
    """Publish discovery config topics"""


@dataclass
class HomeAssistantConfig:
    """Home Assistant integration, the `homeassistant` block"""

    discovery: HomeAssistantDiscoveryConfig = field(default_factory=HomeAssistantDiscoveryConfig)
    """MQTT discovery settings"""
    state_topic_suffix: str = "state"
    """Reserved, the state topic currently always ends in `state`"""
    device_creation: bool = True
    """Group each node's update entities under a Home Assistant device"""
    force_command_topic: bool = False
    """Publish a command topic even where an update can't be installed"""
    extra_attributes: bool = True
    """Source the entity's attributes from the general topic, using `json_attributes_topic`"""
    area: str | None = None
    """Suggested area for the Home Assistant device"""
    release_summary_max_size: int = 6144
    """Characters of release notes to publish before truncating"""


def default_heartbeat_file() -> str:
    """In the system temp dir, which follows TMPDIR, as healthcheck.sh does, and is writable for non-root users"""
    return str(Path(tempfile.gettempdir()) / "updates2mqtt.heartbeat")


@dataclass
class HealthCheckConfig:
    """Heartbeat publishing, the `node.healthcheck` block"""

    enabled: bool = True
    """Publish heartbeats"""
    interval: int = 300
    """Interval in seconds to publish heartbeat message, 0 to disable"""
    topic_template: str = "healthcheck/{node_name}/updates2mqtt"
    """Heartbeat topic, with `{node_name}` replaced by the node name"""
    heartbeat_file: str = field(default_factory=lambda: f"${{oc.env:U2M_HEARTBEAT_FILE,{default_heartbeat_file()}}}")
    """Local file for the container healthcheck, holding when the app last ran its heartbeat, and when the broker
    last acknowledged one, so no separate MQTT connection is needed to check it; empty to not write one.
    `U2M_HEARTBEAT_FILE` sets it for both the app and `healthcheck.sh`, which can't read this config file"""


@dataclass
class NodeConfig:
    """This Updates2MQTT instance, the `node` block"""

    name: str = field(default_factory=lambda: os.getenv("NODE_NAME", os.uname().nodename.replace(".local", "")))
    """Unique name for this instance, used in topics and entity ids, from `NODE_NAME` or the host name"""
    git_path: str = "/usr/bin/git"
    """Path to the git executable, used for local builds"""
    healthcheck: HealthCheckConfig = field(default_factory=HealthCheckConfig)
    """Heartbeat settings"""


@dataclass
class LogConfig:
    """Logging, the `log` block"""

    level: LogLevel = "${oc.decode:${oc.env:U2M_LOG_LEVEL,INFO}}"  # type: ignore[assignment] # pyright: ignore[reportAssignmentType] # ty: ignore[invalid-assignment]
    """Log level, from `U2M_LOG_LEVEL`"""
    json: bool = False
    """Use JSON structured logging for non-interactive running"""


@dataclass
class Config:
    """Root of `config.yaml`"""

    log: LogConfig = field(default_factory=LogConfig)  # pyright: ignore[reportArgumentType, reportCallIssue]
    """Logging"""
    node: NodeConfig = field(default_factory=NodeConfig)
    """This instance"""
    mqtt: MqttConfig = field(default_factory=MqttConfig)  # pyright: ignore[reportArgumentType, reportCallIssue]
    """MQTT broker connection"""
    homeassistant: HomeAssistantConfig = field(default_factory=HomeAssistantConfig)
    """Home Assistant integration"""
    docker: DockerConfig = field(default_factory=DockerConfig)
    """Docker containers"""
    github: GitHubConfig = field(default_factory=GitHubConfig)
    """GitHub API access"""
    scan_interval: int = 60 * 60 * 3
    """Seconds between scans"""
    packages: dict[str, PackageUpdateInfo] = field(default_factory=dict)
    """Package metadata, keyed by package name, adding to or overriding the common packages"""


@dataclass
class CommonPackages:
    """Built-in package metadata, the format of `common_packages.yaml`"""

    common_packages: dict[str, PackageUpdateInfo] = field(default_factory=dict)
    """Package metadata, keyed by package name"""


class IncompleteConfigException(BaseException):
    pass


def is_env_complete_config() -> bool:
    # MQTT credentials are the only settings without a default
    return all(os.environ.get(var) for var in ("MQTT_USER", "MQTT_PASS"))


def is_autogen_config() -> bool:
    env_var: str | None = os.environ.get("U2M_AUTOGEN_CONFIG")
    if env_var:
        return env_var.lower() not in ("no", "0", "false")
    # Explicit setting absent, so only generate a config file if env vars don't fully describe the config
    return not is_env_complete_config()


# U2M_ env vars read directly or via oc.env interpolation in the config dataclasses
KNOWN_U2M_ENV_VARS: frozenset[str] = frozenset(
    (
        "U2M_AUTOGEN_CONFIG",
        "U2M_HEARTBEAT_FILE",
        "U2M_LOG_LEVEL",
        "U2M_MAX_CONCURRENT_UPDATES",
        "U2M_REMOVE_OLD_IMAGE",
    )
)


def unrecognised_env_vars(environ: typing.Mapping[str, str] | None = None) -> list[str]:
    """Env vars that look aimed at Updates2MQTT but that it doesn't use, usually typos or from old blog posts"""
    environ = os.environ if environ is None else environ
    return sorted(k for k in environ if k.startswith("UPDATES2MQTT_") or (k.startswith("U2M_") and k not in KNOWN_U2M_ENV_VARS))


def warn_unrecognised_env_vars(environ: typing.Mapping[str, str] | None = None) -> None:
    for env_var in unrecognised_env_vars(environ):
        log.warning(
            "Ignoring unrecognised environment variable, see https://updates2mqtt.rhizomatics.org.uk/configuration/",
            env_var=env_var,
        )


# settings that hold credentials, as dotted paths into the config file
SECRET_SETTINGS: tuple[str, ...] = (
    "mqtt.password",
    "mqtt.client_key_password",
    "github.access_token",
    "docker.portainer.api_key",
)


def literal_secrets(file_cfg: Any) -> list[str]:
    """Secret settings written into the config file itself, rather than left to an env var interpolation"""
    found: list[str] = []
    raw: Any = OmegaConf.to_container(file_cfg, resolve=False) if OmegaConf.is_config(file_cfg) else file_cfg
    for setting in SECRET_SETTINGS:
        value: Any = raw
        for key in setting.split("."):
            value = value.get(key) if isinstance(value, dict) else None
        if isinstance(value, str) and value and "${" not in value:
            found.append(setting)
    return found


def warn_exposed_secrets(conf_file_path: Path, file_cfg: Any) -> None:
    """Warn if a config file holding secrets can be read by every user on the host"""
    try:
        if conf_file_path.stat().st_mode & 0o004:
            secrets: list[str] = literal_secrets(file_cfg)
            if secrets:
                log.warning(
                    "Config file holds secrets and is readable by all users, restrict it with `chmod 600`, "
                    "or move the secrets to environment variables",
                    path=conf_file_path.as_posix(),
                    settings=secrets,
                )
    except Exception as e:
        log.debug("Unable to check config file permissions: %s", e)


def load_app_config(conf_file_path: Path, return_invalid: bool = False) -> Config | None:
    warn_unrecognised_env_vars()
    base_cfg: DictConfig = OmegaConf.structured(Config)
    if conf_file_path.exists():
        file_cfg: Any = OmegaConf.load(conf_file_path)
        warn_exposed_secrets(conf_file_path, file_cfg)
        cfg: DictConfig = typing.cast("DictConfig", OmegaConf.merge(base_cfg, file_cfg))
    elif is_autogen_config():
        if not conf_file_path.parent.exists():
            try:
                log.debug(f"Creating config directory {conf_file_path.parent} if not already present")
                conf_file_path.parent.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                log.warning("Unable to create config directory: %s", e, path=conf_file_path.parent)
        try:
            # owner only from the start, as secrets are likely to be added to it
            with os.fdopen(os.open(conf_file_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
                f.write(OmegaConf.to_yaml(base_cfg))
            log.info(f"Auto-generated a new config file at {conf_file_path}")
        except Exception as e:
            log.warning("Unable to write config file: %s", e, path=conf_file_path)
        cfg = base_cfg
    else:
        cfg = base_cfg

    try:
        # Validate that all required fields are present, throw exception now rather than when config first used
        OmegaConf.to_container(cfg, throw_on_missing=True)
        OmegaConf.set_readonly(cfg, True)
        config: Config = typing.cast("Config", cfg)

        if config.mqtt.user in ("", MISSING):
            log.info("The config has place holders for MQTT user")
            if not return_invalid:
                return None
        return config
    except (MissingMandatoryValue, ValidationError) as e:
        log.error("Configuration error %s", e, path=conf_file_path.as_posix())
        if return_invalid and cfg is not None:
            return typing.cast("Config", cfg)
        raise
