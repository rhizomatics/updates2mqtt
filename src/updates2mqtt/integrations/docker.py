import datetime
import subprocess
import time
import typing
from collections.abc import AsyncGenerator, Callable
from enum import Enum
from pathlib import Path
from typing import Any, cast

import docker
import docker.errors
import structlog
from docker.models.containers import Container
from hishel.httpx import SyncCacheClient

from updates2mqtt.config import DockerConfig, DockerPackageUpdateInfo, NodeConfig, PackageUpdateInfo, UpdateInfoConfig
from updates2mqtt.model import Discovery, ReleaseProvider

from .git_utils import git_check_update_available, git_pull, git_timestamp, git_trust

if typing.TYPE_CHECKING:
    from docker.models.images import Image, RegistryData

# distinguish docker build from docker pull?

log = structlog.get_logger()
NO_KNOWN_IMAGE = "UNKNOWN"


class DockerComposeCommand(Enum):
    BUILD = "build"
    UP = "up"


def safe_json_dt(t: float | None) -> str | None:
    return time.strftime("%Y-%m-%dT%H:%M:%S.0000", time.gmtime(t)) if t else None


class DockerProvider(ReleaseProvider):
    def __init__(self, cfg: DockerConfig, common_pkg_cfg: UpdateInfoConfig, node_cfg: NodeConfig) -> None:
        super().__init__("docker")
        self.client: docker.DockerClient = docker.from_env()
        self.cfg: DockerConfig = cfg
        self.node_cfg: NodeConfig = node_cfg
        self.common_pkgs: dict[str, PackageUpdateInfo] = common_pkg_cfg.common_packages if common_pkg_cfg else {}
        # TODO: refresh discovered packages periodically
        self.discovered_pkgs: dict[str, PackageUpdateInfo] = self.discover_metadata()

    def update(self, discovery: Discovery) -> bool:
        logger: Any = self.log.bind(container=discovery.name, action="update")
        logger.info("Updating - last at %s", discovery.update_last_attempt)
        discovery.update_last_attempt = time.time()
        self.fetch(discovery)
        restarted = self.restart(discovery)
        logger.info("Updated - recorded at %s", discovery.update_last_attempt)
        return restarted

    def fetch(self, discovery: Discovery) -> None:
        logger = self.log.bind(container=discovery.name, action="fetch")

        image_ref: str | None = discovery.custom.get("image_ref")
        platform: str | None = discovery.custom.get("platform")
        if discovery.custom.get("can_pull") and image_ref:
            logger.info("Pulling", image_ref=image_ref, platform=platform)
            image: Image = self.client.images.pull(image_ref, platform=platform, all_tags=False)
            if image:
                logger.info("Pulled", image_id=image.id, image_ref=image_ref, platform=platform)
            else:
                logger.warn("Unable to pull", image_ref=image_ref, platform=platform)
        elif discovery.can_build:
            compose_path: str | None = discovery.custom.get("compose_path")
            git_repo_path: str | None = discovery.custom.get("git_repo_path")
            if not compose_path or not git_repo_path:
                logger.warn("No compose path or git repo path configured, skipped build")
                return
            if compose_path and not Path(git_repo_path).is_absolute():
                full_repo_path: Path = Path(compose_path) / git_repo_path
            else:
                full_repo_path = Path(git_repo_path)
            if git_check_update_available(full_repo_path, Path(self.node_cfg.git_path)):
                git_pull(full_repo_path, Path(self.node_cfg.git_path))
            if compose_path:
                self.build(discovery, compose_path)
            else:
                logger.warn("No compose path configured, skipped build")

    def build(self, discovery: Discovery, compose_path: str) -> bool:
        logger = self.log.bind(container=discovery.name, action="build")
        logger.info("Building")
        return self.execute_compose(DockerComposeCommand.BUILD, "", compose_path, logger)

    def execute_compose(self, command: DockerComposeCommand, args: str, cwd: str | None, logger: structlog.BoundLogger) -> bool:
        if not cwd or not Path(cwd).is_dir():
            logger.warn("Invalid compose path, skipped %s", command)
            return False
        logger.info(f"Executing compose {command} {args}")
        cmd: str = "docker-compose" if self.cfg.compose_version == "v1" else "docker compose"
        cmd = cmd + " " + command.value
        if args:
            cmd = cmd + " " + args

        proc = subprocess.run(cmd, check=False, shell=True, cwd=cwd)
        if proc.returncode == 0:
            logger.info(f"{command} via compose successful")
            return True
        logger.warn(
            f"{command} failed: %s",
            proc.returncode,
        )
        return False

    def restart(self, discovery: Discovery) -> bool:
        logger = self.log.bind(container=discovery.name, action="restart")
        compose_path = discovery.custom.get("compose_path")
        return self.execute_compose(DockerComposeCommand.UP, "--detach --yes", compose_path, logger)

    def rescan(self, discovery: Discovery) -> Discovery | None:
        logger = self.log.bind(container=discovery.name, action="rescan")
        try:
            c: Container = self.client.containers.get(discovery.name)
            if c:
                rediscovery = self.analyze(c, discovery.session, original_discovery=discovery)
                if rediscovery:
                    self.discoveries[rediscovery.name] = rediscovery
                    return rediscovery
            logger.warn("Unable to find container for rescan")
        except docker.errors.NotFound:
            logger.warn("Container not found in Docker")
        except docker.errors.APIError:
            logger.exception("Docker API error retrieving container")
        return None

    def analyze(self, c: Container, session: str, original_discovery: Discovery | None = None) -> Discovery | None:
        logger = self.log.bind(container=c.name, action="analyze")
        image_ref = None
        image_name = None
        local_versions = None
        if c.attrs is None:
            logger.warn("No container attributes found, discovery rejected")  # type: ignore[unreachable]
            return None
        if c.name is None:
            logger.warn("No container name found, discovery rejected")
            return None

        def env_override(env_var: str, default: Any) -> Any | None:
            return default if c_env.get(env_var) is None else c_env.get(env_var)

        env_str = c.attrs["Config"]["Env"]
        c_env = dict(env.split("=", maxsplit=1) for env in env_str if "==" not in env)
        ignore_container: str | None = env_override("UPD2MQTT_IGNORE", "FALSE")
        if ignore_container and ignore_container.upper() in ("1", "TRUE"):
            logger.info("Container ignored due to UPD2MQTT_IGNORE setting")
            return None

        image: Image | None = c.image
        if image is not None and image.tags and len(image.tags) > 0:
            image_ref = image.tags[0]
        else:
            image_ref = c.attrs.get("Config", {}).get("Image")
        if image_ref is None:
            logger.warn("No image or image attributes found")
        else:
            try:
                image_name = image_ref.split(":")[0]
            except Exception as e:
                logger.warn("No tags found (%s) : %s", image, e)
            if image is not None and image.attrs is not None:
                try:
                    local_versions = [i.split("@")[1][7:19] for i in image.attrs["RepoDigests"]]
                except Exception as e:
                    logger.warn("Cannot determine local version: %s", e)
                    logger.warn("RepoDigests=%s", image.attrs.get("RepoDigests"))

        platform: str = "Unknown"
        pkg_info: PackageUpdateInfo = self.default_metadata(image_name)

        try:
            picture_url = env_override("UPD2MQTT_PICTURE", pkg_info.logo_url)
            relnotes_url = env_override("UPD2MQTT_RELNOTES", pkg_info.release_notes_url)
            if image is not None and image.attrs is not None:
                platform = "/".join(
                    filter(
                        None,
                        [
                            image.attrs["Os"],
                            image.attrs["Architecture"],
                            image.attrs.get("Variant"),
                        ],
                    ),
                )

            reg_data: RegistryData | None = None
            latest_version: str | None = NO_KNOWN_IMAGE
            local_version: str | None = NO_KNOWN_IMAGE

            if image_ref and local_versions:
                retries_left = 3
                while reg_data is None and retries_left > 0 and not self.stopped.is_set():
                    try:
                        reg_data = self.client.images.get_registry_data(image_ref)
                        latest_version = reg_data.short_id[7:] if reg_data else None
                    except docker.errors.APIError as e:
                        retries_left -= 1
                        if retries_left == 0 or e.is_client_error():
                            logger.warn("Failed to fetch registry data: [%s] %s", e.errno, e.explanation)
                        else:
                            logger.debug("Failed to fetch registry data, retrying: %s", e)

            if local_versions:
                # might be multiple RepoDigests if image has been pulled multiple times with diff manifests
                local_version = latest_version if latest_version in local_versions else local_versions[0]

            def save_if_set(key: str, val: datetime.datetime | str | None) -> None:
                if val is not None:
                    custom[key] = val

            image_ref = image_ref or ""

            custom: dict[str, str | datetime.datetime | bool] = {}
            custom["platform"] = platform
            custom["image_ref"] = image_ref
            save_if_set("compose_path", c.labels.get("com.docker.compose.project.working_dir"))
            save_if_set("compose_version", c.labels.get("com.docker.compose.version"))
            save_if_set("git_repo_path", c_env.get("UPD2MQTT_GIT_REPO_PATH"))
            save_if_set("apt_pkgs", c_env.get("UPD2MQTT_APT_PKGS"))

            if c_env.get("UPD2MQTT_UPDATE") == "AUTO":
                logger.debug("Auto update policy detected")
                update_policy = "Auto"
            else:
                update_policy = "Passive"

            if custom.get("git_repo_path") and custom.get("compose_path"):
                full_repo_path: Path = Path(cast("str", custom.get("compose_path"))).joinpath(
                    cast("str", custom.get("git_repo_path"))
                )

                git_trust(full_repo_path, Path(self.node_cfg.git_path))
                save_if_set("git_local_timestamp", git_timestamp(full_repo_path, Path(self.node_cfg.git_path)))
            features: list[str] = []
            can_pull: bool = (
                self.cfg.allow_pull
                and image_ref is not None
                and image_ref != ""
                and (local_version != NO_KNOWN_IMAGE or latest_version != NO_KNOWN_IMAGE)
            )
            can_build: bool = self.cfg.allow_build and custom.get("git_repo_path") is not None
            can_restart: bool = self.cfg.allow_restart and custom.get("compose_path") is not None
            can_update: bool = False
            if can_pull or can_build or can_restart:
                # public install-neutral capabilities and Home Assistant features
                can_update = True
                features.append("INSTALL")
                features.append("PROGRESS")
            if relnotes_url:
                features.append("RELEASE_NOTES")
            custom["can_pull"] = can_pull

            return Discovery(
                self,
                c.name,
                session,
                entity_picture_url=picture_url,
                release_url=relnotes_url,
                current_version=local_version,
                update_policy=update_policy,
                update_last_attempt=(original_discovery and original_discovery.update_last_attempt) or None,
                latest_version=latest_version if latest_version != NO_KNOWN_IMAGE else local_version,
                title_template="Docker image update for {name} on {node}",
                device_icon=self.cfg.device_icon,
                can_update=can_update,
                can_build=can_build,
                can_restart=can_restart,
                status=(c.status == "running" and "on") or "off",
                custom=custom,
                features=features,
            )
        except Exception:
            logger.exception("Docker Discovery Failure", container_attrs=c.attrs)
        return None

    async def scan(self, session: str) -> AsyncGenerator[Discovery]:  # type: ignore  # noqa: PGH003
        logger = self.log.bind(session=session, action="scan")
        containers = results = 0
        for c in self.client.containers.list():
            if self.stopped.is_set():
                logger.info(f"Shutdown detected, aborting scan at {c}")
                break
            containers = containers + 1
            result = self.analyze(cast("Container", c), session)
            if result:
                self.discoveries[result.name] = result
                results = results + 1
                yield result
        logger.info("Completed", container_count=containers, result_count=results)

    def command(self, discovery_name: str, command: str, on_update_start: Callable, on_update_end: Callable) -> bool:
        logger = self.log.bind(container=discovery_name, action="command", command=command)
        logger.info("Executing")
        discovery: Discovery | None = None
        updated: bool = False
        try:
            discovery = self.resolve(discovery_name)
            if not discovery:
                logger.warn("Unknown entity", entity=discovery_name)
            elif command != "install":
                logger.warn("Unknown command")
            else:
                if discovery.can_update:
                    rediscovery: Discovery | None = None
                    logger.info("Starting update ...")
                    on_update_start(discovery)
                    if self.update(discovery):
                        logger.info("Rescanning ...")
                        rediscovery = self.rescan(discovery)
                        updated = rediscovery is not None
                        logger.info("Rescanned %s: %s", updated, rediscovery)
                    else:
                        logger.info("Rescan with no result")
                    on_update_end(rediscovery or discovery)
                else:
                    logger.warning("Update not supported for this container")
        except Exception:
            logger.exception("Failed to handle", discovery_name=discovery_name, command=command)
            if discovery:
                on_update_end(discovery)
        return updated

    def resolve(self, discovery_name: str) -> Discovery | None:
        return self.discoveries.get(discovery_name)

    def hass_state_format(self, discovery: Discovery) -> dict:  # noqa: ARG002
        # disable since hass mqtt update has strict json schema for message
        return {
            # "docker_image_ref": discovery.custom.get("image_ref"),
            # "last_update_attempt": safe_json_dt(discovery.update_last_attempt),
            # "can_pull": discovery.custom.get("can_pull"),
            # "can_build": discovery.custom.get("can_build"),
            # "can_restart": discovery.custom.get("can_restart"),
            # "git_repo_path": discovery.custom.get("git_repo_path"),
            # "compose_path": discovery.custom.get("compose_path"),
            # "platform": discovery.custom.get("platform"),
        }

    def default_metadata(self, image_name: str | None) -> PackageUpdateInfo:
        relnotes_url: str | None = None
        picture_url: str | None = self.cfg.default_entity_picture_url

        if image_name is not None:
            for pkg in self.common_pkgs.values():
                if pkg.docker is not None and pkg.docker.image_name is not None and pkg.docker.image_name == image_name:
                    self.log.debug(
                        "Found common package", pkg=pkg.docker.image_name, logo_url=picture_url, relnotes_url=relnotes_url
                    )
                    return pkg
            for pkg in self.discovered_pkgs.values():
                if pkg.docker is not None and pkg.docker.image_name is not None and pkg.docker.image_name == image_name:
                    self.log.debug(
                        "Found discovered package", pkg=pkg.docker.image_name, logo_url=picture_url, relnotes_url=relnotes_url
                    )
                    return pkg

        self.log.debug("No common or discovered package found", image_name=image_name)
        return PackageUpdateInfo(
            DockerPackageUpdateInfo(image_name or NO_KNOWN_IMAGE), logo_url=picture_url, release_notes_url=relnotes_url
        )

    def discover_metadata(self) -> dict[str, PackageUpdateInfo]:
        pkgs: dict[str, PackageUpdateInfo] = {}
        cfg = self.cfg.discover_metadata.get("linuxserver.io")
        if cfg and cfg.enabled:
            linuxserver_metadata(pkgs, cache_ttl=cfg.cache_ttl)
        return pkgs


def linuxserver_metadata_api(cache_ttl: int) -> dict:
    """Fetch and cache linuxserver.io API call for image metadata"""
    try:
        with SyncCacheClient(headers=[("cache-control", f"max-age={cache_ttl}")]) as client:
            log.debug(f"Fetching linuxserver.io metadata from API, cache_ttl={cache_ttl}")
            req = client.get("https://api.linuxserver.io/api/v1/images?include_config=false&include_deprecated=false")
            return req.json()
    except Exception:
        log.exception("Failed to fetch linuxserver.io metadata")
        return {}


def linuxserver_metadata(discovered_pkgs: dict[str, PackageUpdateInfo], cache_ttl: int) -> None:
    """Fetch linuxserver.io metadata for all their images via their API"""
    repos: list = linuxserver_metadata_api(cache_ttl).get("data", {}).get("repositories", {}).get("linuxserver", [])
    added = 0
    for repo in repos:
        image_name = repo.get("name")
        if image_name and image_name not in discovered_pkgs:
            discovered_pkgs[image_name] = PackageUpdateInfo(
                DockerPackageUpdateInfo(f"lscr.io/linuxserver/{image_name}"),
                logo_url=repo["project_logo"],
                release_notes_url=f"{repo['github_url']}/releases",
            )
            added += 1
            log.debug("Added linuxserver.io package", pkg=image_name)
    log.info(f"Added {added} linuxserver.io package details")
