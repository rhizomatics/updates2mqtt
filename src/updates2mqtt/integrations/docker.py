import asyncio
import os
import random
import re
import socket
import time
import typing
from collections.abc import AsyncGenerator, Awaitable, Callable
from enum import Enum
from functools import partial
from pathlib import Path
from threading import Event
from typing import Any, cast

import docker
import docker.errors
import structlog
from docker.models.containers import Container

from updates2mqtt.config import (
    SEMVER_RE,
    SOURCE_PLATFORM_GITHUB,
    UNKNOWN_VERSION,
    VERSION_RE,
    DockerConfig,
    GitHubConfig,
    NodeConfig,
    PackageUpdateInfo,
    PublishPolicy,
    RegistryAPI,
    UpdatePolicy,
    VersionPolicy,
)
from updates2mqtt.helpers import ProcessResult, Selection, Throttler, run_process
from updates2mqtt.integrations.docker_enrich import (
    CommonPackageEnricher,
    ContainerDistributionAPIVersionLookup,
    DefaultPackageEnricher,
    DockerClientVersionLookup,
    DockerImageInfo,
    DockerServiceDetails,
    HotioPackageEnricher,
    LinuxServerIOPackageEnricher,
    LocalContainerInfo,
    PackageEnricher,
    SourceReleaseEnricher,
)
from updates2mqtt.integrations.github_enrich import GithubReleaseEnricher
from updates2mqtt.integrations.portainer import PortainerClient, is_portainer_image
from updates2mqtt.model import Discovery, ReleaseDetail, ReleaseProvider

from .git_utils import git_check_update_available, git_iso_timestamp, git_local_digest, git_pull, git_trust

if typing.TYPE_CHECKING:
    from docker.models.images import Image

# distinguish docker build from docker pull?

log = structlog.get_logger()


class DockerComposeCommand(Enum):
    BUILD = "build"
    UP = "up"


# Seconds to wait before recreating ourselves on self-bounce, giving the in-flight
# update command time to finish and publish its final (non in-progress) state.
SELF_BOUNCE_DELAY = 5
# Longest to wait on self-bounce for other in-flight updates to finish, since stopping
# this container would kill their compose or git subprocesses part way through
SELF_BOUNCE_DRAIN_TIMEOUT = 600
SELF_BOUNCE_DRAIN_INTERVAL = 1
# Label marking the short-lived container that recreates this one, so scans ignore it
SELF_BOUNCE_HELPER_LABEL = "updates2mqtt.self_update_helper"
# Environment passed to the self-bounce helper, so its docker CLI reaches the same engine
DOCKER_CLIENT_ENV_VARS = ("DOCKER_HOST", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH", "DOCKER_CONTEXT", "DOCKER_CONFIG")
DEFAULT_MAX_CONCURRENT_UPDATES = 3
# Generous, since a compose build can compile a whole image
COMPOSE_TIMEOUT = 60 * 60
# Docker writes per-container files under .../containers/<id>/, bind mounted into the container
CONTAINER_ID_RE = re.compile(r"/containers/([0-9a-f]{64})/")
# Recreation may complete after the restart call returns, e.g. Portainer redeploy,
# so wait for the container to move off the old image before rescanning
RECREATE_WAIT_TIMEOUT = 60
RECREATE_WAIT_INTERVAL = 2


def safe_json_dt(t: float | None) -> str | None:
    return time.strftime("%Y-%m-%dT%H:%M:%S.0000", time.gmtime(t)) if t else None


class ContainerCustomization:
    """Local customization of a Docker container, by label or env var"""

    label_prefix: str = "updates2mqtt."
    env_prefix: str = "UPD2MQTT_"

    def __init__(self, container: Container) -> None:
        self.update: UpdatePolicy = UpdatePolicy.PASSIVE  # was known as UPD2MQTT_UPDATE before policies and labels
        self.git_repo_path: str | None = None
        self.picture: str | None = None
        self.relnotes: str | None = None
        self.ignore: bool = False
        self.version_policy: VersionPolicy | None = None
        self.registry_token: str | None = None

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
                    elif attr == "version_policy":
                        # defaults to None, so the type can't be inferred from the current value
                        setattr(self, attr, VersionPolicy[v.upper()])
                    elif isinstance(getattr(self, attr), UpdatePolicy):
                        setattr(self, attr, UpdatePolicy[v.upper()])
                    else:
                        setattr(self, attr, v)


class DockerProvider(ReleaseProvider):
    def __init__(
        self,
        cfg: DockerConfig,
        node_cfg: NodeConfig,
        packages: dict[str, PackageUpdateInfo] | None = None,
        github_cfg: GitHubConfig | None = None,
        self_bounce: Event | None = None,
    ) -> None:
        super().__init__(node_cfg, "docker")
        self.client: docker.DockerClient = docker.from_env()
        self.cfg: DockerConfig = cfg
        # asyncio primitives bind to the running loop on first use, so safe to create here
        self.update_slots: asyncio.Semaphore = asyncio.Semaphore(self.max_concurrent_updates())
        # compose and Portainer act on a whole project/stack, so serialize those per project
        self.project_locks: dict[str, asyncio.Lock] = {}
        self.active_updates: set[str] = set()
        self.analysis_lock: asyncio.Lock = asyncio.Lock()

        # TODO: refresh discovered packages periodically
        self.throttler = Throttler(self.cfg.default_api_backoff, self.log, self.stopped)
        self.self_bounce: Event | None = self_bounce
        self.portainer: PortainerClient | None = PortainerClient(self.cfg.portainer) if self.cfg.portainer.url else None
        if self.portainer and not self.portainer.enabled:
            self.log.warning("Portainer url configured without api_key, Portainer redeploy disabled")
            self.portainer = None
        if self.portainer and self.cfg.portainer.ca_certs and not Path(self.cfg.portainer.ca_certs).is_file():
            self.log.warning("Portainer ca_certs file not found at %s", self.cfg.portainer.ca_certs)

        self.pkg_enrichers: list[PackageEnricher] = [
            CommonPackageEnricher(self.cfg, packages),
            LinuxServerIOPackageEnricher(self.cfg),
            HotioPackageEnricher(self.cfg),
            DefaultPackageEnricher(self.cfg),
        ]
        self.docker_client_image_lookup = DockerClientVersionLookup(
            self.client, self.throttler, self.cfg.registry, self.cfg.default_api_backoff
        )
        self.registry_image_lookup = ContainerDistributionAPIVersionLookup(self.throttler, self.cfg.registry)
        self.release_enricher = SourceReleaseEnricher()
        if github_cfg:
            self.github_enricher: GithubReleaseEnricher | None = GithubReleaseEnricher(github_cfg)
        else:
            self.github_enricher = None
        self.local_info_builder = LocalContainerInfo()

    def initialize(self) -> None:
        for enricher in self.pkg_enrichers:
            enricher.initialize()
        self.clean_self_bounce_helpers()

    def close(self) -> None:
        self.registry_image_lookup.close()
        self.log.debug("Docker provider initialized")

    def max_concurrent_updates(self) -> int:
        try:
            return max(1, int(self.cfg.max_concurrent_updates))
        except (TypeError, ValueError):
            self.log.warning(
                "Invalid max_concurrent_updates %s, using %s", self.cfg.max_concurrent_updates, DEFAULT_MAX_CONCURRENT_UPDATES
            )
            return DEFAULT_MAX_CONCURRENT_UPDATES

    def is_self_bouncing(self) -> bool:
        return self.self_bounce is not None and self.self_bounce.is_set()

    def project_lock(self, service_info: DockerServiceDetails) -> asyncio.Lock:
        """Compose and Portainer act on the whole project, so concurrent runs on one project could collide"""
        key: str = service_info.compose_project or service_info.compose_path or service_info.container_name or ""
        return self.project_locks.setdefault(key, asyncio.Lock())

    async def update(self, discovery: Discovery) -> bool:
        logger: Any = self.log.bind(container=discovery.name, action="update")
        if discovery.update_last_attempt:
            logger.info("Updating - last at %s", discovery.update_last_attempt)
        else:
            logger.info("Updating - first this session")
        discovery.update_last_attempt = time.time()
        old_image_id: str | None = self.container_image_id(discovery.name)
        new_image_id: str | None = await self.fetch(discovery)
        restarted: bool = await self.restart(discovery)
        if restarted and old_image_id and new_image_id and new_image_id != old_image_id and not self.is_self_bouncing():
            await self.wait_for_recreate(discovery.name, old_image_id)
        if restarted and old_image_id and self.cfg.remove_old_image:
            await asyncio.to_thread(self.remove_old_image, discovery.name, old_image_id)
        logger.info("Updated - recorded at %s", discovery.update_last_attempt)
        return restarted

    def container_image_id(self, container_name: str) -> str | None:
        try:
            return self.client.containers.get(container_name).attrs.get("Image")
        except docker.errors.APIError as e:
            self.log.warning("Unable to find image for container: %s", e, container=container_name)
            return None

    async def wait_for_recreate(self, container_name: str, old_image_id: str) -> bool:
        """Wait for the container to be recreated from a new image, so a rescan doesn't see the old one"""
        logger: Any = self.log.bind(container=container_name, action="wait_for_recreate")
        deadline: float = time.monotonic() + RECREATE_WAIT_TIMEOUT
        while True:
            current_image_id: str | None = self.container_image_id(container_name)
            if current_image_id is not None and current_image_id != old_image_id:
                logger.debug("Container recreated with new image %s", current_image_id)
                return True
            if time.monotonic() >= deadline or self.stopped.is_set():
                logger.warning("Container not recreated with new image after %ss", RECREATE_WAIT_TIMEOUT)
                return False
            await asyncio.sleep(RECREATE_WAIT_INTERVAL)

    def remove_old_image(self, container_name: str, old_image_id: str) -> None:
        """Remove the replaced image, left alone if still in use by any container"""
        logger: Any = self.log.bind(container=container_name, action="remove_old_image", image_id=old_image_id)
        current_image_id: str | None = self.container_image_id(container_name)
        if current_image_id is None or current_image_id == old_image_id:
            # includes self-bounce, where recreation is deferred
            logger.debug("Container not yet using a new image, old image kept")
            return
        try:
            self.client.images.remove(old_image_id)
            logger.info("Removed old image")
        except docker.errors.APIError as e:
            logger.info("Old image not removed: %s", e.explanation or e)

    async def fetch(self, discovery: Discovery) -> str | None:
        """Pull or build the update, returning the id of a newly pulled image"""
        logger = self.log.bind(container=discovery.name, action="fetch")
        installed_info: DockerImageInfo | None = cast("DockerImageInfo|None", discovery.current_detail)
        service_info: DockerServiceDetails | None = cast("DockerServiceDetails|None", discovery.installation_detail)

        image_ref: str | None = installed_info.ref if installed_info else None
        platform: str | None = installed_info.platform if installed_info else None
        if discovery.can_pull and image_ref:
            logger.info("Pulling", image_ref=image_ref, platform=platform)
            # Docker SDK is blocking, so pull in a worker thread to leave the event loop free
            image: Image = await asyncio.to_thread(self.pull_image, image_ref, platform)
            if image:
                logger.info("Pulled", image_id=image.id, image_ref=image_ref, platform=platform)
                return image.id
            logger.warning("Unable to pull", image_ref=image_ref, platform=platform)
        elif discovery.can_build and service_info:
            compose_path: str | None = service_info.compose_path
            git_repo_path: str | None = service_info.git_repo_path
            logger.debug("can_build check", git_repo=git_repo_path)
            if not compose_path or not git_repo_path:
                logger.warning("No compose path or git repo path configured, skipped build")
                return None

            full_repo_path: Path = self.full_repo_path(compose_path, git_repo_path)
            # services in one project often share a repo, so don't pull and build concurrently
            async with self.project_lock(service_info):
                if await git_pull(full_repo_path, Path(self.node_cfg.git_path)):
                    await self.build(discovery)
                else:
                    logger.debug("Skipping git_pull, no update")
        return None

    def pull_image(self, image_ref: str, platform: str | None) -> "Image":
        return self.client.images.pull(image_ref, platform=platform, all_tags=False)

    def full_repo_path(self, compose_path: str | None, git_repo_path: str | None) -> Path:
        if compose_path is None or git_repo_path is None:
            raise ValueError("Unexpected null paths")
        if compose_path and not Path(git_repo_path).is_absolute():
            return Path(compose_path) / git_repo_path
        return Path(git_repo_path)

    async def build(self, discovery: Discovery) -> bool:
        logger = self.log.bind(container=discovery.name, action="build")
        service_info: DockerServiceDetails | None = cast("DockerServiceDetails|None", discovery.installation_detail)

        if not service_info or not service_info.compose_path:
            logger.warning("No service_info available on compose")
            return False
        logger.info("Building", compose_path=service_info.compose_path, service=service_info.compose_service)
        return await self.execute_compose(
            command=DockerComposeCommand.BUILD,
            args=[],
            service=service_info.compose_service,
            cwd=service_info.compose_path,
            logger=logger,
            project=service_info.compose_project,
        )

    def compose_args(
        self, command: DockerComposeCommand, args: list[str], service: str | None, project: str | None = None
    ) -> list[str]:
        cmd: list[str] = ["docker-compose"] if self.cfg.compose_version == "v1" else ["docker", "compose"]
        if project:
            # project name may differ from directory name, e.g. `-p` or Portainer stacks
            cmd.extend(["-p", project])
        cmd.append(command.value)
        cmd.extend(args)
        if service:
            cmd.append(service)
        return cmd

    async def execute_compose(
        self,
        command: DockerComposeCommand,
        args: list[str],
        service: str | None,
        cwd: str | None,
        logger: structlog.BoundLogger,
        project: str | None = None,
    ) -> bool:
        if not cwd or not Path(cwd).is_dir():
            logger.warning("Compose path %s not visible in this container, skipped %s", cwd, command)
            return False

        cmd: list[str] = self.compose_args(command, args, service, project)
        logger.info("Executing %s", " ".join(cmd))
        result: ProcessResult = await run_process(cmd, cwd=cwd, timeout=COMPOSE_TIMEOUT)
        if result.ok:
            logger.info(f"{command.value} via compose successful")
            logger.debug("compose output", stdout=result.stdout, stderr=result.stderr)
            return True
        if self.cfg.compose_version != "v1" and (
            "unknown command: docker compose" in result.stderr or "'compose' is not a docker command" in result.stderr
        ):
            logger.warning("docker compose set to wrong version, seems like v1 installed")
            self.cfg.compose_version = "v1"
        logger.warning(f"{command.value} failed: %s", result.returncode, stderr=result.stderr[-2000:])
        return False

    async def restart(self, discovery: Discovery) -> bool:
        logger = self.log.bind(container=discovery.name, action="restart")
        installed_info: DockerImageInfo | None = cast("DockerImageInfo|None", discovery.current_detail)
        service_info: DockerServiceDetails | None = cast("DockerServiceDetails|None", discovery.installation_detail)

        if service_info is None:
            return False

        recreate: Callable[[], Awaitable[bool]]
        via_portainer: bool = False
        portainer: PortainerClient | None = self.portainer
        stack_id: str | None = service_info.portainer_stack_id
        if self.use_portainer(service_info, installed_info) and portainer and stack_id:
            logger.info("Recreating via Portainer stack %s", stack_id)
            via_portainer = True

            async def redeploy() -> bool:
                # Portainer client is blocking, and waits for the deployment to finish
                return await asyncio.to_thread(portainer.redeploy, stack_id)

            recreate = redeploy
        else:
            recreate = partial(
                self.execute_compose,
                command=DockerComposeCommand.UP,
                args=["--detach", "--yes"],
                service=service_info.compose_service,
                cwd=service_info.compose_path,
                logger=logger,
                project=service_info.compose_project,
            )

        if self.is_self(installed_info, service_info) and self.self_bounce is not None:
            logger.warning("Attempting to self-bounce, deferring recreation by %ss", SELF_BOUNCE_DELAY)
            self.self_bounce.set()
            # Deferred so that the in-flight command handling can finish and publish
            # the final (non in-progress) state before this container is stopped/replaced.
            self.spawn(self.self_bounce_recreate(discovery.name, service_info, recreate, via_portainer), name="self-bounce")
            return True

        async with self.project_lock(service_info):
            return await recreate()

    def is_self(self, installed_info: DockerImageInfo | None, service_info: DockerServiceDetails) -> bool:
        return bool(
            installed_info
            and (
                "ghcr.io/rhizomatics/updates2mqtt" in installed_info.ref
                or (service_info.git_repo_path and service_info.git_repo_path.endswith("updates2mqtt"))
            )
        )

    async def self_bounce_recreate(
        self,
        container_name: str,
        service_info: DockerServiceDetails,
        recreate: Callable[[], Awaitable[bool]],
        via_portainer: bool,
    ) -> None:
        """Recreate this app's own container, from somewhere that survives this container being stopped

        Compose run in this container is killed when compose stops the container, before the replacement
        is started, so a short-lived helper container runs it instead. Portainer redeploys server side.
        """
        logger: Any = self.log.bind(container=container_name, action="self_bounce")
        recreated: bool = False
        try:
            await asyncio.sleep(SELF_BOUNCE_DELAY)
            await self.drain_other_updates(container_name, logger)
            async with self.project_lock(service_info):
                if via_portainer:
                    logger.info("Recreating self via Portainer")
                    recreated = await recreate()
                else:
                    helper: Container | None = await asyncio.to_thread(self.launch_self_bounce_helper, service_info, logger)
                    if helper is not None:
                        await self.wait_for_self_bounce_helper(helper, logger)
                    else:
                        logger.warning("Recreating from inside this container, which may be interrupted as it is stopped")
                        recreated = await recreate()
            if recreated:
                # the replacement container may already be up, and this one is about to be stopped
                return
            logger.error("Self-bounce did not recreate this container, continuing on current version")
        except asyncio.CancelledError:
            # normally shutdown as the helper or Portainer stops this container
            raise
        except Exception:
            logger.exception("Self-bounce failed, continuing on current version")
        if self.self_bounce is not None:
            self.self_bounce.clear()

    async def drain_other_updates(self, container_name: str, logger: Any) -> None:
        """Wait for other in-flight updates, which would be killed part way through as this container stops"""
        deadline: float = time.monotonic() + SELF_BOUNCE_DRAIN_TIMEOUT
        others: set[str] = self.active_updates - {container_name}
        if others:
            logger.info("Waiting for %s other updates to finish before self-bounce: %s", len(others), sorted(others))
        while others:
            if time.monotonic() >= deadline or self.stopped.is_set():
                logger.warning("Self-bounce proceeding with updates still in progress: %s", sorted(others))
                return
            await asyncio.sleep(SELF_BOUNCE_DRAIN_INTERVAL)
            others = self.active_updates - {container_name}

    def own_container(self) -> Container | None:
        """The container this app is running in, if any"""
        candidates: list[str] = []
        try:
            candidates.extend(CONTAINER_ID_RE.findall(Path("/proc/self/mountinfo").read_text()))
        except OSError:
            pass
        if Path("/.dockerenv").exists():
            # hostname defaults to the short container id, unless overridden in compose
            candidates.append(socket.gethostname())
        for candidate in dict.fromkeys(candidates):
            try:
                return self.client.containers.get(candidate)
            except docker.errors.APIError:
                continue
        return None

    def launch_self_bounce_helper(self, service_info: DockerServiceDetails, logger: Any) -> Container | None:
        """Start a detached container, from this one's image and mounts, to run `compose up` on this service"""
        if not service_info.compose_path_found:
            logger.info("Compose path not visible, no helper can recreate this container")
            return None
        own: Container | None = self.own_container()
        if own is None or not own.attrs:
            logger.info("Unable to identify this container, no helper can recreate it")
            return None
        host_config: dict[str, Any] = own.attrs.get("HostConfig") or {}
        config: dict[str, Any] = own.attrs.get("Config") or {}
        image_id: str | None = own.attrs.get("Image")
        if not image_id or not own.id:
            logger.info("No image found for this container, no helper can recreate it")
            return None
        own_name: str = own.name or own.id[:12]
        cmd: list[str] = self.compose_args(
            DockerComposeCommand.UP, ["--detach", "--yes"], service_info.compose_service, service_info.compose_project
        )
        try:
            helper: Container = self.client.containers.run(
                image_id,
                entrypoint=cmd[:1],
                command=cmd[1:],
                working_dir=service_info.compose_path,
                # same docker socket, compose and git paths as this container
                volumes_from=[own.id],
                environment={k: v for k in DOCKER_CLIENT_ENV_VARS if (v := os.environ.get(k))},
                network_mode=host_config.get("NetworkMode") or None,
                user=config.get("User") or None,
                group_add=host_config.get("GroupAdd") or None,
                labels={SELF_BOUNCE_HELPER_LABEL: own_name, "updates2mqtt.ignore": "true"},
                name=f"{own_name}_self_update_{int(time.time())}",
                detach=True,
            )
        except docker.errors.APIError as e:
            logger.warning("Unable to start self-bounce helper container: %s", e)
            return None
        logger.info("Started helper container %s to recreate this container: %s", helper.name, " ".join(cmd))
        return helper

    async def wait_for_self_bounce_helper(self, helper: Container, logger: Any) -> None:
        """Only returns if this container survives the helper, i.e. it wasn't recreated"""
        deadline: float = time.monotonic() + COMPOSE_TIMEOUT
        while time.monotonic() < deadline:
            await asyncio.sleep(RECREATE_WAIT_INTERVAL)
            try:
                await asyncio.to_thread(helper.reload)
            except docker.errors.NotFound:
                logger.warning("Self-bounce helper container removed before finishing")
                return
            if helper.status in ("exited", "dead"):
                await asyncio.to_thread(self.report_self_bounce_helper, helper)
                return
        logger.warning("Self-bounce helper still running after %ss", COMPOSE_TIMEOUT)

    def report_self_bounce_helper(self, helper: Container) -> None:
        """Log the result of a finished helper, and remove it"""
        logger: Any = self.log.bind(action="self_bounce", helper=helper.name)
        exit_code: int | None = (helper.attrs.get("State") or {}).get("ExitCode")
        output: str = ""
        try:
            output = helper.logs(tail=50).decode("utf-8", errors="replace")
        except docker.errors.APIError:
            pass
        if exit_code == 0:
            logger.info("Self-bounce helper completed", exit_code=exit_code)
            logger.debug("Self-bounce helper output", output=output)
        else:
            logger.warning("Self-bounce helper failed", exit_code=exit_code, output=output)
        try:
            helper.remove()
        except docker.errors.APIError as e:
            logger.debug("Unable to remove helper: %s", e)

    def clean_self_bounce_helpers(self) -> None:
        """Report and remove helpers left behind by a previous instance recreating itself"""
        try:
            helpers: list[Container] = self.client.containers.list(
                all=True, filters={"label": SELF_BOUNCE_HELPER_LABEL, "status": "exited"}
            )
        except docker.errors.APIError as e:
            self.log.debug("Unable to list self-bounce helpers: %s", e)
            return
        for helper in helpers:
            self.report_self_bounce_helper(helper)

    def use_portainer(self, service_info: DockerServiceDetails, installed_info: DockerImageInfo | None) -> bool:
        """Portainer redeploy only when compose can't be run directly"""
        return (
            self.portainer is not None
            and not service_info.compose_path_found
            and service_info.portainer_stack_id is not None
            and not is_portainer_image(installed_info.ref if installed_info else None)
        )

    async def rescan(self, discovery: Discovery) -> Discovery | None:
        logger: Any = self.log.bind(container=discovery.name, action="rescan")
        try:
            c: Container = await asyncio.to_thread(self.client.containers.get, discovery.name)
            if c:
                rediscovery: Discovery | None = await self.analyze_off_loop(c, discovery.session, previous_discovery=discovery)
                if rediscovery and not rediscovery.throttled:
                    self.discoveries[rediscovery.name] = rediscovery
                    return rediscovery
            logger.warning("Unable to find container for rescan")
        except docker.errors.NotFound:
            logger.warning("Container not found in Docker")
        except docker.errors.APIError:
            logger.exception("Docker API error retrieving container")
        return None

    async def analyze_off_loop(
        self, c: Container, session: str, previous_discovery: Discovery | None = None
    ) -> Discovery | None:
        """Analysis makes blocking registry, GitHub, Docker and git calls, so runs in a worker thread

        One at a time, as the enrichers, throttler and API stats aren't safe to share across threads
        """
        async with self.analysis_lock:
            return await asyncio.to_thread(self.analyze, c, session, previous_discovery)

    def analyze(self, c: Container, session: str, previous_discovery: Discovery | None = None) -> Discovery | None:
        logger = self.log.bind(container=c.name, action="analyze")

        if c.attrs is None or not c.attrs:
            logger.warning("No container attributes found, discovery rejected")
            return None
        if c.name is None:
            logger.warning("No container name found, discovery rejected")
            return None

        customization: ContainerCustomization = ContainerCustomization(c)
        if customization.ignore:
            logger.info("Container ignored due to UPD2MQTT_IGNORE setting")
            return None

        if customization.update == UpdatePolicy.AUTO:
            logger.debug("Auto update policy detected")
        update_policy: UpdatePolicy = customization.update or UpdatePolicy.PASSIVE

        local_info: DockerImageInfo
        service_info: DockerServiceDetails
        local_info, service_info = self.local_info_builder.build_image_info(c)
        pkg_info: PackageUpdateInfo = self.default_metadata(local_info)

        version_policy: VersionPolicy
        if customization.version_policy:
            logger.debug("Overriding version_policy to local customization: %s", customization.version_policy)
            version_policy = customization.version_policy
        else:
            if self.cfg.version_policy == VersionPolicy.AUTO and pkg_info.docker:
                logger.debug(
                    "Version policy, pkg level %s, config level: %s", pkg_info.docker.version_policy, self.cfg.version_policy
                )
                version_policy = pkg_info.docker.version_policy or self.cfg.version_policy
            else:
                logger.debug("Version policy, fixed config level: %s", self.cfg.version_policy)
                version_policy = self.cfg.version_policy

        try:
            service_info.git_repo_path = customization.git_repo_path

            registry_selection = Selection(self.cfg.registry_select, local_info.index_name)
            latest_info: DockerImageInfo
            if local_info.pinned:
                logger.debug("Skipping registry fetch for local pinned image, %s", local_info.ref)
                latest_info = local_info.reuse()
            elif registry_selection and local_info.ref and not local_info.local_build:
                if self.cfg.registry.api == RegistryAPI.DOCKER_CLIENT:
                    latest_info = self.docker_client_image_lookup.lookup(local_info)
                elif self.cfg.registry.api == RegistryAPI.OCI_V2:
                    latest_info = self.registry_image_lookup.lookup(local_info, token=customization.registry_token)
                elif self.cfg.registry.api == RegistryAPI.OCI_V2_MINIMAL:
                    latest_info = self.registry_image_lookup.lookup(
                        local_info, token=customization.registry_token, minimal=True
                    )
                else:  # assuming RegistryAPI.DISABLED
                    logger.debug(f"Skipping registry check, disabled in config {self.cfg.registry.api}")
                    latest_info = local_info.reuse()
            elif local_info.local_build:
                # assume its a locally built image if no RepoDigests available
                latest_info = local_info.reuse()
                latest_info.short_digest = None
                latest_info.image_digest = None
                latest_info.config_digest = None
            else:
                logger.debug("Registry selection rules suppressed metadata lookup")
                latest_info = local_info.reuse()

            release_info: ReleaseDetail | None = self.release_enricher.enrich(
                latest_info,
                source_repo_url=pkg_info.source_repo_url,
                notes_url=customization.relnotes or pkg_info.release_notes_url,
            )
            logger.debug("Enriched release info: %s", release_info)

            if latest_info.image_digest and release_info:
                if self.github_enricher and release_info.source_platform == SOURCE_PLATFORM_GITHUB:
                    self.github_enricher.enrich(latest_info, release_info)
                else:
                    self.log.debug("Not a github release or no github configured")

            if service_info.git_repo_path and service_info.compose_path:
                full_repo_path: Path = Path(service_info.compose_path).joinpath(service_info.git_repo_path)

                git_trust(full_repo_path, Path(self.node_cfg.git_path))
                service_info.git_local_timestamp = git_iso_timestamp(full_repo_path, Path(self.node_cfg.git_path))

            can_pull: bool = (
                self.cfg.allow_pull
                and not local_info.local_build
                and local_info.ref is not None
                and local_info.ref != ""
                and (local_info.short_digest is not None or latest_info.short_digest is not None)
            )
            if self.cfg.allow_pull and not can_pull:
                logger.debug(
                    f"Pull unavailable, ref:{local_info.ref},local:{local_info.short_digest},latest:{latest_info.short_digest}"
                )

            can_build: bool = False
            if self.cfg.allow_build:
                can_build = service_info.git_repo_path is not None and service_info.compose_path is not None
                if not can_build:
                    if service_info.git_repo_path is not None:
                        logger.debug(
                            "Local build ignored for git_repo_path=%s because no compose_path", service_info.git_repo_path
                        )
                else:
                    full_repo_path = self.full_repo_path(service_info.compose_path, service_info.git_repo_path)
                    if local_info.local_build and full_repo_path:
                        git_versionish = git_local_digest(full_repo_path, Path(self.node_cfg.git_path))
                        if git_versionish:
                            local_info.git_digest = git_versionish
                            logger.debug("Git digest for local code %s", git_versionish)

                            behind_count: int = git_check_update_available(full_repo_path, Path(self.node_cfg.git_path))
                            if behind_count > 0:
                                latest_info.git_digest = f"{git_versionish}+{behind_count}"
                                logger.info("Git update available, generating version %s", latest_info.git_digest)
                            else:
                                logger.debug(f"Git update not available, local repo:{full_repo_path}")
                                latest_info.git_digest = git_versionish

            can_restart: bool = self.cfg.allow_restart and (
                service_info.compose_path_found or self.use_portainer(service_info, local_info)
            )
            if self.cfg.allow_restart and service_info.compose_path and not can_restart and previous_discovery is None:
                if service_info.portainer_stack_id:
                    logger.warning(
                        "Compose path %s is inside Portainer's data volume (stack %s), "
                        "configure Portainer API access to allow restart",
                        service_info.compose_path,
                        service_info.portainer_stack_id,
                    )
                else:
                    logger.warning(
                        "Compose path %s not visible in this container, map it as a volume to allow restart",
                        service_info.compose_path,
                    )

            if can_pull:
                update_type = "Docker Image"
            elif can_build:
                update_type = "Docker Build"
            else:
                update_type = "Unavailable"

            # can_pull,can_build etc are only info flags
            # the HASS update process is driven by comparing current and available versions

            public_installed_version: str
            public_latest_version: str
            version_basis: str
            public_installed_version, public_latest_version, version_basis = select_versions(
                version_policy, local_info, latest_info
            )

            publish_policy: PublishPolicy = PublishPolicy.HOMEASSISTANT
            img_ref_selection = Selection(self.cfg.image_ref_select, local_info.ref)
            version_selection = Selection(self.cfg.version_select, latest_info.version)
            if not img_ref_selection or not version_selection:
                self.log.info(
                    "Excluding from HA Discovery for include/exclude rule: %s, %s", local_info.ref, latest_info.version
                )
                publish_policy = PublishPolicy.MQTT

            discovery: Discovery = Discovery(
                self,
                c.name,
                session,
                node=self.node_cfg.name,
                entity_picture_url=customization.picture or pkg_info.logo_url,
                current_version=public_installed_version,
                publish_policy=publish_policy,
                update_policy=update_policy,
                version_policy=version_policy,
                version_basis=version_basis,
                latest_version=public_latest_version,
                device_icon=self.cfg.device_icon,
                can_pull=can_pull,
                update_type=update_type,
                can_build=can_build,
                can_restart=can_restart,
                status=(c.status == "running" and "on") or "off",
                throttled=latest_info.throttled,
                previous=previous_discovery,
                release_detail=release_info,
                installation_detail=service_info,
                current_detail=local_info,
                latest_detail=latest_info,
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

    async def scan(self, session: str, shuffle: bool = True) -> AsyncGenerator[Discovery]:
        logger = self.log.bind(session=session, action="scan", source=self.source_type)
        containers: int = 0
        results: int = 0
        throttled: int = 0

        targets: list[Container] = await asyncio.to_thread(self.client.containers.list)
        if shuffle:
            random.shuffle(targets)
        logger.debug("Starting scanning %s containers", len(targets))
        for c in targets:
            logger.debug("Analyzing container", container=c.name)
            if self.stopped.is_set():
                logger.info(f"Shutdown detected, aborting scan at {c}")
                break
            if is_compose_recreate_name(c):
                logger.debug("Skipping container being recreated by compose", container=c.name)
                continue
            containers = containers + 1
            result: Discovery | None = await self.analyze_off_loop(c, session)
            if result:
                logger.debug("Analyzed container", result_name=result.name, throttled=result.throttled)
                self.discoveries[result.name] = result
                results = results + 1
                throttled += 1 if result.throttled else 0
                yield result
            else:
                logger.debug("No result from analysis", container=c.name)
        logger.info("Completed", container_count=containers, throttled_count=throttled, result_count=results)

    async def command(
        self,
        discovery_name: str,
        command: str,
        on_update_start: Callable[[Discovery], None],
        on_update_end: Callable[[Discovery], None],
    ) -> bool:
        logger = self.log.bind(container=discovery_name, action="command", command=command)
        logger.info("Executing Command")
        discovery: Discovery | None = None
        updated: bool = False
        in_progress: Discovery | None = None
        try:
            discovery = self.resolve(discovery_name)
            if not discovery:
                logger.warning("Unknown entity", entity=discovery_name)
            elif command != "install":
                logger.warning("Unknown command")
            elif self.is_self_bouncing():
                # this container is about to be replaced, which would kill the update part way through
                logger.warning("Self update pending, command ignored")
            elif discovery.can_update:
                rediscovery: Discovery | None = None
                # shown as installing while queued for a free update slot
                on_update_start(discovery)
                in_progress = discovery
                self.active_updates.add(discovery_name)
                try:
                    async with self.update_slots:
                        logger.info("Starting update ...")
                        if await self.update(discovery):
                            logger.debug("Rescanning ...")
                            rediscovery = await self.rescan(discovery)
                            updated = rediscovery is not None and not rediscovery.throttled
                            logger.info("Rescanned, updated:%s", updated)
                        else:
                            logger.info("Rescan with no result")
                finally:
                    self.active_updates.discard(discovery_name)
                in_progress = rediscovery or discovery
                on_update_end(in_progress)
                in_progress = None
            else:
                logger.warning("Update not supported for this container")
        except Exception:
            logger.exception("Failed to handle", discovery_name=discovery_name, command=command)
        finally:
            if in_progress:
                on_update_end(in_progress)
        return updated

    def resolve(self, discovery_name: str) -> Discovery | None:
        return self.discoveries.get(discovery_name)

    def default_metadata(self, image_info: DockerImageInfo) -> PackageUpdateInfo:
        for enricher in self.pkg_enrichers:
            pkg_info: PackageUpdateInfo | None = enricher.enrich(image_info)
            if pkg_info is not None:
                return pkg_info
        raise ValueError("No enricher could provide metadata, not even default enricher")


def is_compose_recreate_name(container: Container) -> bool:
    """Compose renames the old container to `<12 char id>_<name>` while recreating it"""
    name: Any = container.name
    container_id: Any = container.id
    if not isinstance(name, str) or not isinstance(container_id, str) or len(container_id) < 12:
        return False
    return name.startswith(f"{container_id[:12]}_")


def comparable_digests(installed: DockerImageInfo, latest: DockerImageInfo) -> tuple[str | None, str | None]:
    """Short digests of the same kind for installed and latest

    A local image id is its config digest, while a registry lookup's image digest is its manifest digest,
    so compare config digests where both are known, otherwise the short digests
    """
    if installed.config_digest and latest.config_digest:
        return installed.condense_digest(installed.config_digest), latest.condense_digest(latest.config_digest)
    return installed.short_digest, latest.short_digest


def select_versions(version_policy: VersionPolicy, installed: DockerImageInfo, latest: DockerImageInfo) -> tuple[str, str, str]:
    """Pick the best version string to display based on the version policy and available data

    Ensures that both local installed and remote latest versions are derived in same way
    Falls back to digest if version not reliable or not consistent with current/available version
    """
    phase: int = 0
    shortcircuit: str | None = None

    def basis(rule: str) -> str:
        return f"{rule}-{phase}" if not shortcircuit else f"{rule}-{phase}-{shortcircuit}"

    #
    # Detect No Update Available
    # --------------------------
    #
    # shortcircuit the logic if there's nothing to compare
    #
    installed_digest, latest_digest = comparable_digests(installed, latest)
    if latest.throttled:
        log.debug("Flattening versions for throttled update %s", installed.ref)
        shortcircuit = "THR"
        latest = installed
    elif not any((latest.short_digest, latest.repo_digest, latest.git_digest, latest.version)):
        log.debug("Flattening versions for empty update %s", installed.ref)
        shortcircuit = "NUP"
        latest = installed
    elif latest_digest is not None and latest_digest == installed_digest:
        log.debug("Flattening versions for identical update %s", installed.ref)
        shortcircuit = "SDM"
        latest = installed
    elif installed.image_digest in latest.repo_digests:
        # TODO: avoid this by better adaptations for different registries and single/multi manifests
        log.debug(
            "Matching new repo_digest against installed image digest for %s image %s", installed.index_name, installed.name
        )
        shortcircuit = "FGA"
        latest = installed
    elif latest.image_digest in installed.repo_digests:
        # TODO: avoid this by better adaptations for different registries and single/multi manifests
        log.debug(
            "Matching new image_digest against installed repo digest for %s image %s", installed.index_name, installed.name
        )
        shortcircuit = "FGB"
        latest = installed

    #
    # Explicit Policy Choice
    # ----------------------
    #

    if version_policy == VersionPolicy.VERSION and installed.version and latest.version:
        return installed.version, latest.version, basis("version")

    installed_digest, latest_digest = comparable_digests(installed, latest)
    installed_digest_available: bool = installed_digest is not None and installed_digest != ""
    latest_digest_available: bool = latest_digest is not None and latest_digest != ""
    matching_digest: bool = installed_digest_available and latest_digest_available and installed_digest == latest_digest
    changed_digest: bool = installed_digest_available and latest_digest_available and installed_digest != latest_digest

    if version_policy == VersionPolicy.DIGEST and installed_digest_available and latest_digest_available:
        return installed_digest, latest_digest, basis("digest")  # type: ignore[return-value]
    if (
        version_policy == VersionPolicy.VERSION_DIGEST
        and installed.version
        and latest.version
        and installed_digest_available
        and latest_digest_available
    ):
        return (
            f"{installed.version}:{installed_digest}",
            f"{latest.version}:{latest_digest}",
            basis("version-digest"),
        )

    if (
        version_policy == VersionPolicy.TIMESTAMP
        and installed.created
        and latest.created
        and (
            (latest.created > installed.created and changed_digest) or (latest.created == installed.created and matching_digest)
        )
    ):
        return installed.created, latest.created, basis("timestamp")

    #
    # Auto Policy - Humane Versions
    # -----------------------------
    #
    phase = 1
    if (
        version_policy == VersionPolicy.AUTO
        and installed.version
        and latest.version
        and (
            (installed.version == latest.version and matching_digest)
            or (installed.version != latest.version and changed_digest)
        )
    ):
        # detect semver, or v semver (e.g. v1.030)
        # only use this if both version and digest are consistently agreeing or disagreeing
        # if the strict conditions work, people see nice version numbers on screen rather than hashes
        if re.fullmatch(SEMVER_RE, installed.version or "") and re.fullmatch(SEMVER_RE, latest.version or ""):
            # Smells like semver, override if not using version_policy
            return installed.version, latest.version, basis("semver")
        if re.fullmatch(VERSION_RE, installed.version or "") and re.fullmatch(VERSION_RE, latest.version or ""):
            # Smells like casual semver, override if not using version_policy
            return installed.version, latest.version, basis("casualver")

    if (
        version_policy == VersionPolicy.AUTO
        and installed.tag
        and latest.tag
        and ((installed.tag == latest.tag and matching_digest) or (installed.tag != latest.tag and changed_digest))
    ):
        if re.fullmatch(SEMVER_RE, installed.tag) and re.fullmatch(SEMVER_RE, latest.tag):
            return installed.tag, latest.tag, basis("semver-tag")
        if re.fullmatch(SEMVER_RE, installed.tag) and re.fullmatch(SEMVER_RE, latest.tag):
            return installed.tag, latest.tag, basis("semver-tag")

    #
    # Local Builds
    # ------------
    #
    phase = 2
    if installed.git_digest and latest.git_digest:
        return f"git:{installed.git_digest}", f"git:{latest.git_digest}", basis("git")

    #
    #  Fall Back - Qualified Versions
    # --------------------------------
    #
    phase = 3
    if (
        installed.version
        and latest.version
        and (
            # same version with a changed digest is a rebuild, the digest qualifier shows it
            (installed.version == latest.version and (matching_digest or changed_digest))
            or (installed.version != latest.version and changed_digest)
        )
    ):
        return (
            f"{installed.version}:{installed_digest}",
            f"{latest.version}:{latest_digest}",
            basis("version-digest"),
        )

    #
    # Fall Back - Timestamp, Digest, Version
    # --------------------------------------

    phase = 4
    if (
        installed.created
        and latest.created
        and (
            (latest.created > installed.created and changed_digest) or (latest.created == installed.created and matching_digest)
        )
    ):
        return installed.created, latest.created, basis("timestamp")
    if installed_digest_available and latest_digest_available:
        return installed_digest, latest_digest, basis("digest")  # type: ignore[return-value]
    if installed.version and not latest.version and not latest.short_digest and not latest.repo_digest:
        return installed.version, installed.version, basis("version")

    #
    # Fall Back - Missing Digests
    # ---------------------------
    phase = 5
    if not installed_digest_available and latest_digest_available:
        # odd condition if local image has no identity, even out versions so no update alert
        return latest_digest, latest_digest, basis("digest")  # type: ignore[return-value]

    #
    # Fall Back - Repo Digests
    # ---------------------------
    phase = 6

    def condense_repo_id(i: DockerImageInfo) -> str:
        v: str | None = i.condense_digest(i.repo_digest) if i.repo_digest else None
        return v or ""

    if installed.repo_digest and latest.repo_digest:
        # where the image digest isn't available, fall back to a repo digest
        return condense_repo_id(installed), condense_repo_id(latest), basis("repo-digest")

    phase = 7
    if latest.repo_digest and latest.repo_digest in installed.repo_digests:
        # installed has multiple RepoDigests from multiple pulls and one of them matches latest current repo digest
        return condense_repo_id(latest), condense_repo_id(latest), basis("repo-digest")

    if installed_digest_available and not latest_digest_available:
        # no new digest, so latest is the current
        return installed_digest, installed_digest, basis("digest")  # type: ignore[return-value]

    #
    # Failure to Find Any Version
    # ---------------------------
    #
    log.warning("No versions can be determined for %s", installed.ref)
    phase = 999
    return UNKNOWN_VERSION, UNKNOWN_VERSION, basis("failure")
