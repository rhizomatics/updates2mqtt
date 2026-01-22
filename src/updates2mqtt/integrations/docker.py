import random
import re
import subprocess
import time
import typing
from collections.abc import AsyncGenerator, Callable
from enum import Enum
from pathlib import Path
from threading import Event
from typing import Any, cast

import docker
import docker.errors
import structlog
from docker.models.containers import Container

from updates2mqtt.config import (
    SEMVER_RE,
    UNKNOWN_VERSION,
    VERSION_RE,
    DockerConfig,
    NodeConfig,
    PackageUpdateInfo,
    PublishPolicy,
    RegistryAccessPolicy,
    UpdatePolicy,
    VersionPolicy,
)
from updates2mqtt.helpers import Selection, Throttler
from updates2mqtt.integrations.docker_enrich import (
    CommonPackageEnricher,
    ContainerDistributionAPIVersionLookup,
    DefaultPackageEnricher,
    DockerClientVersionLookup,
    DockerImageInfo,
    LinuxServerIOPackageEnricher,
    LocalContainerInfo,
    PackageEnricher,
    SourceReleaseEnricher,
)
from updates2mqtt.model import Discovery, ReleaseProvider

from .git_utils import git_check_update_available, git_iso_timestamp, git_local_digest, git_pull, git_trust

if typing.TYPE_CHECKING:
    from docker.models.images import Image

# distinguish docker build from docker pull?

log = structlog.get_logger()


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
                    elif isinstance(getattr(self, attr), VersionPolicy):
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
        self_bounce: Event | None = None,
    ) -> None:
        super().__init__(node_cfg, "docker")
        self.client: docker.DockerClient = docker.from_env()
        self.cfg: DockerConfig = cfg

        # TODO: refresh discovered packages periodically
        self.throttler = Throttler(self.cfg.default_api_backoff, self.log, self.stopped)
        self.self_bounce: Event | None = self_bounce
        self.pkg_enrichers: list[PackageEnricher] = [
            CommonPackageEnricher(self.cfg),
            LinuxServerIOPackageEnricher(self.cfg),
            DefaultPackageEnricher(self.cfg),
        ]
        self.docker_client_image_lookup = DockerClientVersionLookup(self.client, self.throttler, self.cfg.default_api_backoff)
        self.registry_image_lookup = ContainerDistributionAPIVersionLookup(self.throttler)
        self.release_enricher = SourceReleaseEnricher()
        self.local_info_builder = LocalContainerInfo(self.cfg.registry_access)

    def initialize(self) -> None:
        for enricher in self.pkg_enrichers:
            enricher.initialize()

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
            or (discovery.custom.get("git_repo_path") and discovery.custom.get("git_repo_path", "").endswith("updates2mqtt"))
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

    def analyze(self, c: Container, session: str, previous_discovery: Discovery | None = None) -> Discovery | None:
        logger = self.log.bind(container=c.name, action="analyze")

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
        version_policy: VersionPolicy = VersionPolicy.AUTO if not customization.version_policy else customization.version_policy
        if customization.update == UpdatePolicy.AUTO:
            logger.debug("Auto update policy detected")
        update_policy: UpdatePolicy = customization.update or UpdatePolicy.PASSIVE

        local_info: DockerImageInfo = self.local_info_builder.build_image_info(c)
        pkg_info: PackageUpdateInfo = self.default_metadata(local_info)

        try:
            picture_url: str | None = customization.picture or pkg_info.logo_url
            relnotes_url: str | None = customization.relnotes or pkg_info.release_notes_url
            release_summary: str | None = None

            custom: dict[str, str | bool | int | list[str] | dict[str, Any] | None] = {}
            custom.update(local_info.custom)

            custom["platform"] = local_info.platform
            custom["image_ref"] = local_info.ref
            custom["current_image_id"] = local_info.short_digest
            custom["index_name"] = local_info.index_name
            custom["git_repo_path"] = customization.git_repo_path

            registry_selection = Selection(self.cfg.registry_select, local_info.index_name)
            latest_info: DockerImageInfo
            if local_info.pinned:
                logger.debug("Skipping registry fetch for local pinned image, %s", local_info.ref)
                latest_info = local_info.reuse()
            elif registry_selection and local_info.ref and not local_info.local_build:
                if self.cfg.registry_access == RegistryAccessPolicy.DOCKER_CLIENT:
                    latest_info = self.docker_client_image_lookup.lookup(local_info)
                elif self.cfg.registry_access == RegistryAccessPolicy.OCI_V2:
                    latest_info = self.registry_image_lookup.lookup(local_info, token=customization.registry_token)
                else:  # assuming RegistryAccessPolicy.DISABLED
                    logger.debug(f"Skipping registry check, disabled in config {self.cfg.registry_access}")
                    latest_info = local_info.reuse()
            elif local_info.local_build:
                # assume its a locally built image if no RepoDigests available
                latest_info = local_info.reuse()
                latest_info.short_digest = None
                latest_info.image_digest = None
                custom["git_repo_path"] = customization.git_repo_path
            else:
                logger.debug("Registry selection rules suppressed metadata lookup")
                latest_info = local_info.reuse()

            custom.update(latest_info.custom)
            custom["latest_origin"] = latest_info.origin
            custom["latest_image_id"] = latest_info.short_digest

            release_info: dict[str, str | None] = self.release_enricher.enrich(
                latest_info, source_repo_url=pkg_info.source_repo_url, release_url=relnotes_url
            )
            logger.debug("Enriched release info: %s", release_info)

            if release_info.get("release_url") and customization.relnotes is None:
                relnotes_url = release_info.pop("release_url")
            if release_info.get("release_summary"):
                release_summary = release_info.pop("release_summary")

            custom.update(release_info)

            if custom.get("git_repo_path") and custom.get("compose_path"):
                full_repo_path: Path = Path(cast("str", custom.get("compose_path"))).joinpath(
                    cast("str", custom.get("git_repo_path"))
                )

                git_trust(full_repo_path, Path(self.node_cfg.git_path))
                custom["git_local_timestamp"] = git_iso_timestamp(full_repo_path, Path(self.node_cfg.git_path))

            features: list[str] = []
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
                can_build = custom.get("git_repo_path") is not None and custom.get("compose_path") is not None
                if not can_build:
                    if custom.get("git_repo_path") is not None:
                        logger.debug(
                            "Local build ignored for git_repo_path=%s because no compose_path", custom.get("git_repo_path")
                        )
                else:
                    full_repo_path = self.full_repo_path(
                        cast("str", custom.get("compose_path")), cast("str", custom.get("git_repo_path"))
                    )
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

            can_restart: bool = self.cfg.allow_restart and custom.get("compose_path") is not None

            can_update: bool = False

            if can_pull or can_build or can_restart:
                # public install-neutral capabilities and Home Assistant features
                can_update = True
                features.append("INSTALL")
                features.append("PROGRESS")
            elif any((self.cfg.allow_build, self.cfg.allow_restart, self.cfg.allow_pull)):
                logger.info(f"Update not available, can_pull:{can_pull}, can_build:{can_build},can_restart:{can_restart}")
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

            public_installed_version: str
            public_latest_version: str
            version_rule: str
            public_installed_version, public_latest_version, version_rule = select_versions(
                version_policy, local_info, latest_info
            )
            custom["version_rule"] = version_rule

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
                entity_picture_url=picture_url,
                release_url=relnotes_url,
                release_summary=release_summary,
                current_version=public_installed_version,
                publish_policy=publish_policy,
                update_policy=update_policy,
                version_policy=version_policy,
                latest_version=public_latest_version,
                device_icon=self.cfg.device_icon,
                can_update=can_update,
                update_type=update_type,
                can_build=can_build,
                can_restart=can_restart,
                status=(c.status == "running" and "on") or "off",
                custom=custom,
                features=features,
                throttled=latest_info.throttled,
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

    async def scan(self, session: str, shuffle: bool = True) -> AsyncGenerator[Discovery]:
        logger = self.log.bind(session=session, action="scan", source=self.source_type)
        containers: int = 0
        results: int = 0
        throttled: int = 0

        targets: list[Container] = self.client.containers.list()
        if shuffle:
            random.shuffle(targets)
        logger.debug("Starting scanning %s containers", len(targets))
        for c in targets:
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

    def default_metadata(self, image_info: DockerImageInfo) -> PackageUpdateInfo:
        for enricher in self.pkg_enrichers:
            pkg_info = enricher.enrich(image_info)
            if pkg_info is not None:
                return pkg_info
        raise ValueError("No enricher could provide metadata, not even default enricher")


def select_versions(version_policy: VersionPolicy, installed: DockerImageInfo, latest: DockerImageInfo) -> tuple[str, str, str]:
    """Pick the best version string to display based on the version policy and available data

    Ensures that both local installed and remote latest versions are derived in same way
    Falls back to digest if version not reliable or not consistent with current/available version
    """
    phase: int = 0
    shortcircuit: str | None = None

    def basis(rule: str) -> str:
        return f"{rule}-{phase}" if not shortcircuit else f"{rule}-{phase}-{shortcircuit}"

    # shortcircuit the logic if there's nothing to compare
    if latest.throttled:
        log.debug("Flattening versions for throttled update %s", installed.ref)
        shortcircuit = "T"
        latest = installed
    elif not any((latest.short_digest, latest.repo_digest, latest.git_digest, latest.version)):
        log.debug("Flattening versions for empty update %s", installed.ref)
        shortcircuit = "E"
        latest = installed
    elif latest.short_digest == installed.short_digest and latest.short_digest is not None:
        log.debug("Flattening versions for identical update %s", installed.ref)
        shortcircuit = "M"
        latest = installed
    elif installed.image_digest in latest.repo_digests or latest.image_digest in installed.repo_digests:
        # TODO: avoid this by better adaptations for different registries and single/multi manifests
        log.info(
            "Switching round repo and image digests to cope with %s inconsistencies %s", installed.index_name, installed.name
        )
        shortcircuit = "H"
        latest = installed

    if version_policy == VersionPolicy.VERSION and installed.version and latest.version:
        return installed.version, latest.version, basis("version")

    installed_digest_available: bool = installed.short_digest is not None and installed.short_digest != ""
    latest_digest_available: bool = latest.short_digest is not None and latest.short_digest != ""

    if version_policy == VersionPolicy.DIGEST and installed_digest_available and latest_digest_available:
        return installed.short_digest, latest.short_digest, basis("digest")  # type: ignore[return-value]
    if (
        version_policy == VersionPolicy.VERSION_DIGEST
        and installed.version
        and latest.version
        and installed_digest_available
        and latest_digest_available
    ):
        return (
            f"{installed.version}:{installed.short_digest}",
            f"{latest.version}:{latest.short_digest}",
            basis("version-digest"),
        )

    phase = 1
    if version_policy == VersionPolicy.AUTO and (
        (installed.version == latest.version and installed.short_digest == latest.short_digest)
        or (installed.version != latest.version and installed.short_digest != latest.short_digest)
    ):
        # detect semver, or casual semver (e.g. v1.030)
        # only use this if both version and digest are consistently agreeing or disagreeing
        # if the strict conditions work, people see nice version numbers on screen rather than hashes
        if (
            installed.version
            and re.match(SEMVER_RE, installed.version or "")
            and latest.version
            and re.match(SEMVER_RE, latest.version or "")
        ):
            # Smells like semver, override if not using version_policy
            return installed.version, latest.version, basis("semver")
        if (
            installed.version
            and re.match(VERSION_RE, installed.version or "")
            and latest.version
            and re.match(VERSION_RE, latest.version or "")
        ):
            # Smells like casual semver, override if not using version_policy
            return installed.version, latest.version, basis("causualver")

    # AUTO or fallback
    phase = 2
    if installed.version and latest.version and installed_digest_available and latest_digest_available:
        return (
            f"{installed.version}:{installed.short_digest}",
            f"{latest.version}:{latest.short_digest}",
            basis("version-digest"),
        )

        # and ((other_digest is None and other_version is None) or (other_digest is not None and other_version is not None))

    if installed.version and latest.version:
        return installed.version, latest.version, basis("version")

    # Check for local builds
    phase = 3
    if installed.git_digest and latest.git_digest:
        return f"git:{installed.git_digest}", f"git:{latest.git_digest}", basis("git")

    # Fall back to digests, image or repo index
    phase = 4
    if installed_digest_available and latest_digest_available:
        return installed.short_digest, latest.short_digest, basis("digest")  # type: ignore[return-value]
    if installed.version and not latest.version and not latest.short_digest and not latest.repo_digest:
        return installed.version, installed.version, basis("version")
    phase = 5
    if not installed_digest_available and latest_digest_available:
        # odd condition if local image has no identity, even out versions so no update alert
        return latest.short_digest, latest.short_digest, basis("digest")  # type: ignore[return-value]

    # Fall back to repo digests
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
        return installed.short_digest, latest.short_digest, basis("digest")  # type: ignore[return-value]

    log.warn("No versions can be determined for %s", installed.ref)
    phase = 999
    return UNKNOWN_VERSION, UNKNOWN_VERSION, basis("failure")
