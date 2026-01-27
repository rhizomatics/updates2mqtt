import json
import time
from abc import abstractmethod
from collections.abc import AsyncGenerator, Callable
from threading import Event
from typing import Any

import structlog

from updates2mqtt.config import NodeConfig, PublishPolicy, UpdatePolicy, VersionPolicy
from updates2mqtt.helpers import sanitize_name, timestamp


class DiscoveryArtefactDetail:
    """Provider specific detail"""

    def as_dict(self) -> dict[str, str | list | dict | bool | int | None]:
        return {}


class DiscoveryInstallationDetail:
    """Provider specific detail"""

    @abstractmethod
    def as_dict(self) -> dict[str, str | list | dict | bool | int | None]:
        return {}


class ReleaseDetail:
    """The artefact source details

    Note this may be an actual software package, or the source details of the wrapping of it
    For example, some Docker images report the main source repo, and others where the Dockerfile deploy project lives
    """

    def __init__(self, notes_url: str | None = None, summary: str | None = None) -> None:
        self.source_platform: str | None = None
        self.source_repo_url: str | None = None
        self.source_url: str | None = None
        self.version: str | None = None
        self.revision: str | None = None
        self.diff_url: str | None = None
        self.notes_url: str | None = notes_url
        self.title: str | None = None
        self.summary: str | None = summary
        self.net_score: int | None = None

    def as_dict(self) -> dict[str, str | None]:
        return {
            "title": self.title,
            "version": self.version,
            "source_platform": self.source_platform,
            "source_repo": self.source_repo_url,
            "source": self.source_url,
            "revision": self.revision,
            "diff_url": self.diff_url,
            "notes_url": self.notes_url,
            "summary": self.summary,
            "net_score": str(self.net_score) if self.net_score is not None else None,
        }

    def __str__(self) -> str:
        """Log friendly"""
        return ",".join(f"{k}:{v}" for k, v in self.as_dict().items())


class Discovery:
    """Discovered component from a scan"""

    def __init__(
        self,
        provider: "ReleaseProvider",
        name: str,
        session: str,
        node: str,
        entity_picture_url: str | None = None,
        current_version: str | None = None,
        latest_version: str | None = None,
        can_build: bool = False,
        can_restart: bool = False,
        can_pull: bool = False,
        status: str = "on",
        publish_policy: PublishPolicy = PublishPolicy.HOMEASSISTANT,
        update_type: str | None = "Update",
        update_policy: UpdatePolicy = UpdatePolicy.PASSIVE,
        version_policy: VersionPolicy = VersionPolicy.AUTO,
        version_basis: str | None = None,
        title_template: str = "{discovery.update_type} for {discovery.name} on {discovery.node}",
        device_icon: str | None = None,
        custom: dict[str, Any] | None = None,
        throttled: bool = False,
        previous: "Discovery|None" = None,
        release_detail: ReleaseDetail | None = None,
        installation_detail: DiscoveryInstallationDetail | None = None,
        current_detail: DiscoveryArtefactDetail | None = None,
        latest_detail: DiscoveryArtefactDetail | None = None,
    ) -> None:
        self.provider: ReleaseProvider = provider
        self.source_type: str = provider.source_type
        self.session: str = session
        self.name: str = sanitize_name(name)
        self.node: str = node
        self.entity_picture_url: str | None = entity_picture_url
        self.current_version: str | None = current_version
        self.latest_version: str | None = latest_version
        self.can_pull: bool = can_pull
        self.can_build: bool = can_build
        self.can_restart: bool = can_restart
        self.title_template: str | None = title_template
        self.device_icon: str | None = device_icon
        self.update_type: str | None = update_type
        self.status: str = status
        self.publish_policy: PublishPolicy = publish_policy
        self.update_policy: UpdatePolicy = update_policy
        self.version_policy: VersionPolicy = version_policy
        self.version_basis: str | None = version_basis
        self.update_last_attempt: float | None = None
        self.custom: dict[str, Any] = custom or {}
        self.throttled: bool = throttled
        self.scan_count: int
        self.first_timestamp: float
        self.last_timestamp: float = time.time()
        self.check_timestamp: float | None = time.time()
        self.release_detail: ReleaseDetail | None = release_detail
        self.current_detail: DiscoveryArtefactDetail | None = current_detail
        self.latest_detail: DiscoveryArtefactDetail | None = latest_detail
        self.installation_detail: DiscoveryInstallationDetail | None = installation_detail

        if previous:
            self.update_last_attempt = previous.update_last_attempt
            self.first_timestamp = previous.first_timestamp
            self.scan_count = previous.scan_count + 1
        else:
            self.first_timestamp = time.time()
            self.scan_count = 1
        if throttled and previous:
            # roll forward last non-throttled check
            self.check_timestamp = previous.check_timestamp
        elif not throttled:
            self.check_timestamp = time.time()

    def __repr__(self) -> str:
        """Build a custom string representation"""
        return f"Discovery('{self.name}','{self.source_type}',current={self.current_version},latest={self.latest_version})"

    def __str__(self) -> str:
        """Dump the attrs"""

        def stringify(v: Any) -> str | int | float | bool:
            return str(v) if not isinstance(v, (str, int, float, bool)) else v

        dump = {k: stringify(v) for k, v in self.__dict__.items()}
        return json.dumps(dump)

    @property
    def can_update(self) -> bool:
        return self.can_pull or self.can_build or self.can_restart

    @property
    def features(self) -> list[str]:
        results = []
        if self.can_update:
            # public install-neutral capabilities and Home Assistant features
            results.append("INSTALL")
            results.append("PROGRESS")
        if self.release_detail and self.release_detail.notes_url:
            results.append("RELEASE_NOTES")
        return results

    @property
    def title(self) -> str:
        if self.title_template:
            return self.title_template.format(discovery=self)
        return self.name

    def as_dict(self) -> dict[str, str | list | dict | bool | int | None]:
        results: dict[str, str | list | dict | bool | int | None] = {
            "name": self.name,
            "node": self.node,
            "provider": {"source_type": self.provider.source_type},
            "first_scan": {"timestamp": timestamp(self.first_timestamp)},
            "last_scan": {"timestamp": timestamp(self.last_timestamp), "session": self.session, "throttled": self.throttled},
            "scan_count": self.scan_count,
            "installed_version": self.current_version,
            "latest_version": self.latest_version,
            "version_basis": self.version_basis,
            "title": self.title,
            "can_update": self.can_update,
            "can_build": self.can_build,
            "can_restart": self.can_restart,
            "device_icon": self.device_icon,
            "update_type": self.update_type,
            "status": self.status,
            "features": self.features,
            "entity_picture_url": self.entity_picture_url,
            "update_policy": str(self.update_policy),
            "publish_policy": str(self.publish_policy),
            "version_policy": str(self.version_policy),
            "update": {"last_attempt": timestamp(self.update_last_attempt), "in_progress": False},
            "installation_detail": self.installation_detail.as_dict() if self.installation_detail else None,
            "current_detail": self.current_detail.as_dict() if self.current_detail else None,
            "latest_detail": self.latest_detail.as_dict() if self.latest_detail else None,
        }
        if self.release_detail:
            results["release"] = self.release_detail.as_dict() if self.release_detail else None
        if self.custom:
            results[self.source_type] = self.custom
        return results


class ReleaseProvider:
    """Abstract base class for release providers, such as container scanners or package managers API calls"""

    def __init__(self, node_cfg: NodeConfig, source_type: str = "base") -> None:
        self.source_type: str = source_type
        self.discoveries: dict[str, Discovery] = {}
        self.node_cfg: NodeConfig = node_cfg
        self.log: Any = structlog.get_logger().bind(integration=self.source_type)
        self.stopped = Event()

    def initialize(self) -> None:
        """Initialize any loops or background tasks, make any startup API calls"""
        pass

    def stop(self) -> None:
        """Stop any loops or background tasks"""
        self.log.info("Asking release provider to stop", source_type=self.source_type)
        self.stopped.set()

    def __str__(self) -> str:
        """Stringify"""
        return f"{self.source_type} Discovery"

    @abstractmethod
    def update(self, discovery: Discovery) -> bool:
        """Attempt to update the component version"""

    @abstractmethod
    def rescan(self, discovery: Discovery) -> Discovery | None:
        """Rescan a previously discovered component"""

    @abstractmethod
    async def scan(self, session: str) -> AsyncGenerator[Discovery]:
        """Scan for components to monitor"""
        # force recognition as an async generator
        if False:
            yield 0  # type: ignore[unreachable]

    @abstractmethod
    def command(self, discovery_name: str, command: str, on_update_start: Callable, on_update_end: Callable) -> bool:
        """Execute a command on a discovered component"""

    @abstractmethod
    def resolve(self, discovery_name: str) -> Discovery | None:
        """Resolve a discovered component by name"""
