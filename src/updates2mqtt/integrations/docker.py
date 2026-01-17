import subprocess
import time
import typing
from collections.abc import AsyncGenerator, Callable
from enum import Enum
from http import HTTPStatus
from pathlib import Path
from threading import Event
from typing import Any, cast

import docker
import docker.errors
import structlog
from docker.auth import resolve_repository_name
from docker.models.containers import Container
from hishel.httpx import SyncCacheClient
from httpx import Response

from updates2mqtt.config import (
    DockerConfig,
    DockerPackageUpdateInfo,
    NodeConfig,
    PackageUpdateInfo,
    PublishPolicy,
    UpdatePolicy,
)
from updates2mqtt.model import Discovery, ReleaseProvider, Selection

from .git_utils import git_check_update_available, git_iso_timestamp, git_local_version, git_pull, git_trust

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


class ContainerCustomization:
    """Local customization of a Docker container, by label or env var"""

    label_prefix: str = "updates2mqtt."
    env_prefix: str = "UPD2MQTT_"

    def __init__(self, container: Container) -> None:
        self.update: str = "PASSIVE"
        self.git_repo_path: str | None = None
        self.picture: str | None = None
        self.relnotes: str | None = None
        self.ignore: bool = False

        if not container.attrs or container.attrs.get("Config") is None:
            return
        env_pairs: list[str] = container.attrs.get("Config", {}).get("Env")
        if env_pairs:
            c_env: dict[str, str] = dict(env.split("=", maxsplit=1) for env in env_pairs if "==" not in env)
        else:
            c_env = {}

        for attr in dir(self):
            if "__" not in attr:
                label = f"{self.label_prefix}{attr.lower()}"
                env_var = f"{self.env_prefix}{attr.upper()}"
                v: Any = None
                if label in container.labels:
                    # precedence to labels
                    v = container.labels.get(label)
                    log.debug(
                        "%s set from label %s=%s",
                        attr,
                        label,
                        v,
                        integration="docker",
                        container=container.name,
                        action="customize",
                    )
                elif env_var in c_env:
                    v = c_env[env_var]
                    log.debug(
                        "%s set from env var %s=%s",
                        attr,
                        env_var,
                        v,
                        integration="docker",
                        container=container.name,
                        action="customize",
                    )
                if v is not None:
                    if isinstance(getattr(self, attr), bool):
                        setattr(self, attr, v.upper() in ("TRUE", "YES", "1"))
                    else:
                        setattr(self, attr, v)

        self.update = self.update.upper()


class DockerProvider(ReleaseProvider):
    def __init__(
        self,
        cfg: DockerConfig,
        common_pkg_cfg: dict[str, PackageUpdateInfo],
        node_cfg: NodeConfig,
        self_bounce: Event | None = None,
    ) -> None:
        super().__init__(node_cfg, "docker", common_pkg_cfg)
        self.client: docker.DockerClient = docker.from_env()
        self.cfg: DockerConfig = cfg

        # TODO: refresh discovered packages periodically
        self.discovered_pkgs: dict[str, PackageUpdateInfo] = self.discover_metadata()
        self.pause_api_until: dict[str, float] = {}
        self.api_throttle_pause: int = cfg.default_api_backoff
        self.self_bounce: Event | None = self_bounce

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
            logger.debug("can_build check", git_repo=git_repo_path)
            if not compose_path or not git_repo_path:
                logger.warn("No compose path or git repo path configured, skipped build")
                return

            full_repo_path: Path = self.full_repo_path(compose_path, git_repo_path)
            if git_pull(full_repo_path, Path(self.node_cfg.git_path)):
                if compose_path:
                    self.build(discovery, compose_path)
                else:
                    logger.warn("No compose path configured, skipped build")
            else:
                logger.debug("Skipping git_pull, no update")

    def full_repo_path(self, compose_path: str, git_repo_path: str) -> Path:
        if compose_path is None or git_repo_path is None:
            raise ValueError("Unexpected null paths")
        if compose_path and not Path(git_repo_path).is_absolute():
            return Path(compose_path) / git_repo_path
        return Path(git_repo_path)

    def build(self, discovery: Discovery, compose_path: str) -> bool:
        logger = self.log.bind(container=discovery.name, action="build")
        logger.info("Building", compose_path=compose_path)
        return self.execute_compose(
            command=DockerComposeCommand.BUILD,
            args="",
            service=discovery.custom.get("compose_service"),
            cwd=compose_path,
            logger=logger,
        )

    def execute_compose(
        self, command: DockerComposeCommand, args: str, service: str | None, cwd: str | None, logger: structlog.BoundLogger
    ) -> bool:
        if not cwd or not Path(cwd).is_dir():
            logger.warn("Invalid compose path, skipped %s", command)
            return False

        cmd: str = "docker-compose" if self.cfg.compose_version == "v1" else "docker compose"
        logger.info(f"Executing {cmd} {command} {args} {service}")
        cmd = cmd + " " + command.value
        if args:
            cmd = cmd + " " + args
        if service:
            cmd = cmd + " " + service

        proc: subprocess.CompletedProcess[str] = subprocess.run(cmd, check=False, shell=True, cwd=cwd, text=True)
        if proc.returncode == 0:
            logger.info(f"{command} via compose successful")
            return True
        if proc.stderr and "unknown command: docker compose" in proc.stderr:
            logger.warning("docker compose set to wrong version, seems like v1 installed")
            self.cfg.compose_version = "v1"
        logger.warn(
            f"{command} failed: %s",
            proc.returncode,
        )
        return False

    def restart(self, discovery: Discovery) -> bool:
        logger = self.log.bind(container=discovery.name, action="restart")
        if self.self_bounce is not None and (
            "ghcr.io/rhizomatics/updates2mqtt" in discovery.custom.get("image_ref", "")
            or discovery.custom.get("git_repo_path", "").endswith("updates2mqtt")
        ):
            logger.warning("Attempting to self-bounce")
            self.self_bounce.set()
        compose_path = discovery.custom.get("compose_path")
        compose_service: str | None = discovery.custom.get("compose_service")
        return self.execute_compose(
            command=DockerComposeCommand.UP, args="--detach --yes", service=compose_service, cwd=compose_path, logger=logger
        )

    def rescan(self, discovery: Discovery) -> Discovery | None:
        logger = self.log.bind(container=discovery.name, action="rescan")
        try:
            c: Container = self.client.containers.get(discovery.name)
            if c:
                rediscovery = self.analyze(c, discovery.session, previous_discovery=discovery)
                if rediscovery:
                    self.discoveries[rediscovery.name] = rediscovery
                    return rediscovery
            logger.warn("Unable to find container for rescan")
        except docker.errors.NotFound:
            logger.warn("Container not found in Docker")
        except docker.errors.APIError:
            logger.exception("Docker API error retrieving container")
        return None

    def check_throttle(self, repo_id: str) -> bool:
        if self.pause_api_until.get(repo_id) is not None:
            if self.pause_api_until[repo_id] < time.time():
                del self.pause_api_until[repo_id]
                log.info("%s throttling wait complete", repo_id)
            else:
                log.debug("%s throttling has %s secs left", repo_id, self.pause_api_until[repo_id] - time.time())
                return True
        return False

    def analyze(self, c: Container, session: str, previous_discovery: Discovery | None = None) -> Discovery | None:
        logger = self.log.bind(container=c.name, action="analyze")

        image_ref: str | None = None
        image_name: str | None = None
        local_versions = None
        if c.attrs is None or not c.attrs:
            logger.warn("No container attributes found, discovery rejected")
            return None
        if c.name is None:
            logger.warn("No container name found, discovery rejected")
            return None

        customization: ContainerCustomization = ContainerCustomization(c)
        if customization.ignore:
            logger.info("Container ignored due to UPD2MQTT_IGNORE setting")
            return None

        image: Image | None = c.image
        repo_id: str = "DEFAULT"
        if image is not None and image.tags and len(image.tags) > 0:
            image_ref = image.tags[0]
        else:
            image_ref = c.attrs.get("Config", {}).get("Image")
        if image_ref is None:
            logger.warn("No image or image attributes found")
        else:
            repo_id, _ = resolve_repository_name(image_ref)
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

        selection = Selection(self.cfg.image_ref_select, image_ref)
        publish_policy: PublishPolicy = PublishPolicy.MQTT if not selection.result else PublishPolicy.HOMEASSISTANT

        if customization.update == "AUTO":
            logger.debug("Auto update policy detected")
            update_policy: UpdatePolicy = UpdatePolicy.AUTO
        else:
            update_policy = UpdatePolicy.PASSIVE

        platform: str = "Unknown"
        pkg_info: PackageUpdateInfo = self.default_metadata(image_name, image_ref=image_ref)

        try:
            picture_url: str | None = customization.picture or pkg_info.logo_url
            relnotes_url: str | None = customization.relnotes or pkg_info.release_notes_url
            net_score: int | None = None
            release_summary: str | None = None

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
            latest_version_tags: list[str] | Any = []
            registry_throttled = self.check_throttle(repo_id)

            if image_ref and local_versions and not registry_throttled:
                retries_left = 3
                while reg_data is None and retries_left > 0 and not self.stopped.is_set():
                    try:
                        logger.debug("Fetching registry data", image_ref=image_ref)
                        reg_data = self.client.images.get_registry_data(image_ref)
                        log.debug(
                            "Registry Data: id:%s,image:%s, attrs:%s",
                            reg_data.id,
                            reg_data.image_name,
                            reg_data.attrs,
                        )
                        latest_version = reg_data.short_id[7:] if reg_data else None
                        latest_version_tags = reg_data.attrs
                    except docker.errors.APIError as e:
                        if e.status_code == HTTPStatus.TOO_MANY_REQUESTS:
                            retry_secs: int
                            try:
                                retry_secs = int(e.response.headers.get("Retry-After", self.api_throttle_pause))  # type: ignore[union-attr]
                            except:  # noqa: E722
                                retry_secs = self.api_throttle_pause
                            logger.warn("Docker Registry throttling requests for %s seconds, %s", retry_secs, e.explanation)
                            self.pause_api_until[repo_id] = time.time() + retries_left
                            return None
                        retries_left -= 1
                        if retries_left == 0 or e.is_client_error():
                            logger.warn("Failed to fetch registry data: [%s] %s", e.errno, e.explanation)
                        else:
                            logger.debug("Failed to fetch registry data, retrying: %s", e)

            local_version: str | None = NO_KNOWN_IMAGE
            if local_versions:
                # might be multiple RepoDigests if image has been pulled multiple times with diff manifests
                local_version = latest_version if latest_version in local_versions else local_versions[0]
                log.debug(f"Setting local version to {local_version}, local_versions:{local_versions}")

            def save_if_set(key: str, val: str | None) -> None:
                if val is not None:
                    custom[key] = val

            image_ref = image_ref or ""

            custom: dict[str, str | bool | int | list[str] | dict[str, Any] | None] = {}
            custom["platform"] = platform
            custom["image_ref"] = image_ref
            custom["repo_id"] = repo_id
            custom["tags"] = latest_version_tags
            if registry_throttled:
                custom["registry_throttled"] = True
            save_if_set("compose_path", c.labels.get("com.docker.compose.project.working_dir"))
            save_if_set("compose_version", c.labels.get("com.docker.compose.version"))
            save_if_set("compose_service", c.labels.get("com.docker.compose.service"))
            save_if_set("documentation_url", c.labels.get("org.opencontainers.image.documentation"))
            save_if_set("description", c.labels.get("org.opencontainers.image.description"))
            save_if_set("created", c.labels.get("opencontainers.image.created"))
            image_version: str = c.labels.get("org.opencontainers.image.version")
            image_revision: str = c.labels.get("org.opencontainers.image.revision")
            source = c.labels.get("org.opencontainers.image.source")
            if source and image_revision and "github.com" in source:
                diff_url = f"{source}/commit/{image_revision}"
                if self.validate_url(diff_url):
                    save_if_set("diff_url", diff_url)
            if source and image_version and "github.com" in source:
                release_url = f"{source}/releases/tag/{image_version}"
                if self.validate_url(release_url):
                    save_if_set("release_url", release_url)
                    if customization.relnotes is None:
                        # override default pkg info with more precise release notes
                        relnotes_url = release_url
                    base_api = source.replace("https://github.com", "https://api.github.com/repos")
                    api_response: Response | None = self.fetch_url(f"{base_api}/releases/tags/{image_version}")
                    if api_response:
                        api_results = api_response.json()
                        release_summary = api_results.get("body")
                        reactions = api_results.get("reactions")
                        if reactions:
                            net_score = reactions.get("+1", 0) - reactions.get("-1", 0)

            save_if_set("image_version", image_version)
            save_if_set("git_repo_path", customization.git_repo_path)
            custom["net_score"] = net_score

            # save_if_set("apt_pkgs", c_env.get("UPD2MQTT_APT_PKGS"))

            if custom.get("git_repo_path") and custom.get("compose_path"):
                full_repo_path: Path = Path(cast("str", custom.get("compose_path"))).joinpath(
                    cast("str", custom.get("git_repo_path"))
                )

                git_trust(full_repo_path, Path(self.node_cfg.git_path))
                save_if_set("git_local_timestamp", git_iso_timestamp(full_repo_path, Path(self.node_cfg.git_path)))
            features: list[str] = []
            can_pull: bool = (
                self.cfg.allow_pull
                and image_ref is not None
                and image_ref != ""
                and (local_version != NO_KNOWN_IMAGE or latest_version != NO_KNOWN_IMAGE)
            )
            if self.cfg.allow_pull and not can_pull:
                logger.debug(
                    f"Pull not available, image_ref:{image_ref},local_version:{local_version},latest_version:{latest_version}"
                )

            can_build: bool = False
            if self.cfg.allow_build:
                can_build = custom.get("git_repo_path") is not None and custom.get("compose_path") is not None
                if not can_build:
                    if custom.get("git_repo_path") is not None:
                        log.debug(
                            "Local build ignored for git_repo_path=%s because no compose_path", custom.get("git_repo_path")
                        )
                else:
                    full_repo_path = self.full_repo_path(
                        cast("str", custom.get("compose_path")), cast("str", custom.get("git_repo_path"))
                    )
                    if local_version is None or local_version == NO_KNOWN_IMAGE:
                        local_version = git_local_version(full_repo_path, Path(self.node_cfg.git_path)) or NO_KNOWN_IMAGE

                    behind_count: int = git_check_update_available(full_repo_path, Path(self.node_cfg.git_path))
                    if behind_count > 0:
                        if local_version is not None and local_version.startswith("git:"):
                            latest_version = f"{local_version}+{behind_count}"
                            log.info("Git update available, generating version %s", latest_version)
                    else:
                        logger.debug(f"Git update not available, local repo:{full_repo_path}")

            can_restart: bool = self.cfg.allow_restart and custom.get("compose_path") is not None

            can_update: bool = False

            if can_pull or can_build or can_restart:
                # public install-neutral capabilities and Home Assistant features
                can_update = True
                features.append("INSTALL")
                features.append("PROGRESS")
            elif any((self.cfg.allow_build, self.cfg.allow_restart, self.cfg.allow_pull)):
                logger.info(f"Update not available, can_pull:{can_pull}, can_build:{can_build},can_restart{can_restart}")
            if relnotes_url:
                features.append("RELEASE_NOTES")
            if can_pull:
                update_type = "Docker Image"
            elif can_build:
                update_type = "Docker Build"
            else:
                update_type = "Unavailable"
            custom["can_pull"] = can_pull
            # can_pull,can_build etc are only info flags
            # the HASS update process is driven by comparing current and available versions

            discovery: Discovery = Discovery(
                self,
                c.name,
                session,
                node=self.node_cfg.name,
                entity_picture_url=picture_url,
                release_url=relnotes_url,
                release_summary=release_summary,
                current_version=local_version,
                publish_policy=publish_policy,
                update_policy=update_policy,
                latest_version=latest_version if latest_version != NO_KNOWN_IMAGE else local_version,
                device_icon=self.cfg.device_icon,
                can_update=can_update,
                update_type=update_type,
                can_build=can_build,
                can_restart=can_restart,
                status=(c.status == "running" and "on") or "off",
                custom=custom,
                features=features,
                throttled=registry_throttled,
                previous=previous_discovery,
            )
            logger.debug("Analyze generated discovery: %s", discovery)
            return discovery
        except Exception:
            logger.exception("Docker Discovery Failure", container_attrs=c.attrs)
        logger.debug("Analyze returned empty discovery")
        return None

    # def version(self, c: Container, version_type: str):
    #    metadata_version: str = c.labels.get("org.opencontainers.image.version")
    #    metadata_revision: str = c.labels.get("org.opencontainers.image.revision")

    def fetch_url(self, url: str, cache_ttl: int = 300) -> Response | None:
        try:
            with SyncCacheClient(headers=[("cache-control", f"max-age={cache_ttl}")]) as client:
                log.debug(f"Fetching URL {url}, cache_ttl={cache_ttl}")
                response: Response = client.get(url)
            return response
        except Exception as e:
            log.debug("URL %s failed to fetch: %s", url, e)
        return None

    def validate_url(self, url: str, cache_ttl: int = 300) -> bool:
        response = self.fetch_url(url, cache_ttl=cache_ttl)
        return response is not None and response.is_success

    async def scan(self, session: str) -> AsyncGenerator[Discovery]:
        logger = self.log.bind(session=session, action="scan", source=self.source_type)
        containers: int = 0
        results: int = 0
        throttled: int = 0
        logger.debug("Starting container scan loop")
        for c in self.client.containers.list():
            logger.debug("Analyzing container", container=c.name)
            if self.stopped.is_set():
                logger.info(f"Shutdown detected, aborting scan at {c}")
                break
            containers = containers + 1
            result: Discovery | None = self.analyze(c, session)
            if result:
                logger.debug("Analyzed container", result_name=result.name, custom=result.custom)
                self.discoveries[result.name] = result
                results = results + 1
                throttled += 1 if result.throttled else 0
                yield result
            else:
                logger.debug("No result from analysis", container=c.name)
        logger.info("Completed", container_count=containers, throttled_count=throttled, result_count=results)

    def command(self, discovery_name: str, command: str, on_update_start: Callable, on_update_end: Callable) -> bool:
        logger = self.log.bind(container=discovery_name, action="command", command=command)
        logger.info("Executing Command")
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

    def default_metadata(self, image_name: str | None, image_ref: str | None) -> PackageUpdateInfo:
        def match(pkg: PackageUpdateInfo) -> bool:
            if pkg is not None and pkg.docker is not None and pkg.docker.image_name is not None:
                if image_name is not None and image_name == pkg.docker.image_name:
                    return True
                if image_ref is not None and image_ref == pkg.docker.image_name:
                    return True
            return False

        if image_name is not None and image_ref is not None:
            for pkg in self.common_pkg_cfg.values():
                if match(pkg):
                    self.log.debug(
                        "Found common package",
                        image_name=pkg.docker.image_name,  # type: ignore [union-attr]
                        logo_url=pkg.logo_url,
                        relnotes_url=pkg.release_notes_url,
                    )
                    return pkg
            for pkg in self.discovered_pkgs.values():
                if match(pkg):
                    self.log.debug(
                        "Found discovered package",
                        pkg=pkg.docker.image_name,  # type: ignore [union-attr]
                        logo_url=pkg.logo_url,
                        relnotes_url=pkg.release_notes_url,
                    )
                    return pkg

        self.log.debug("No common or discovered package found", image_name=image_name)
        return PackageUpdateInfo(
            DockerPackageUpdateInfo(image_name or NO_KNOWN_IMAGE),
            logo_url=self.cfg.default_entity_picture_url,
            release_notes_url=None,
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
