import datetime as dt
import json
import re
import time
from abc import abstractmethod
from collections.abc import AsyncGenerator, Callable
from threading import Event
from typing import Any

import structlog
from tzlocal import get_localzone

from updates2mqtt.config import NodeConfig, PackageUpdateInfo, PublishPolicy, Selector, UpdatePolicy


def timestamp(time_value: float | None) -> str | None:
    if time_value is None:
        return None
    try:
        return dt.datetime.fromtimestamp(time_value, tz=get_localzone()).isoformat()
    except:  # noqa: E722
        return None


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
        can_update: bool = False,
        can_build: bool = False,
        can_restart: bool = False,
        status: str = "on",
        publish_policy: PublishPolicy = PublishPolicy.HOMEASSISTANT,
        update_type: str | None = "Update",
        update_policy: UpdatePolicy = UpdatePolicy.PASSIVE,
        release_url: str | None = None,
        release_summary: str | None = None,
        title_template: str = "{discovery.update_type} for {discovery.name} on {discovery.node}",
        device_icon: str | None = None,
        custom: dict[str, Any] | None = None,
        features: list[str] | None = None,
        throttled: bool = False,
        previous: "Discovery|None" = None,
    ) -> None:
        self.provider: ReleaseProvider = provider
        self.source_type: str = provider.source_type
        self.session: str = session
        self.name: str = name
        self.node: str = node
        self.entity_picture_url: str | None = entity_picture_url
        self.current_version: str | None = current_version
        self.latest_version: str | None = latest_version
        self.can_update: bool = can_update
        self.can_build: bool = can_build
        self.can_restart: bool = can_restart
        self.release_url: str | None = release_url
        self.release_summary: str | None = release_summary
        self.title_template: str | None = title_template
        self.device_icon: str | None = device_icon
        self.update_type: str | None = update_type
        self.status: str = status
        self.publish_policy: PublishPolicy = publish_policy
        self.update_policy: UpdatePolicy = update_policy
        self.update_last_attempt: float | None = None
        self.custom: dict[str, Any] = custom or {}
        self.features: list[str] = features or []
        self.throttled: bool = throttled
        self.scan_count: int
        self.first_timestamp: float
        self.last_timestamp: float = time.time()

        if previous:
            self.update_last_attempt = previous.update_last_attempt
            self.first_timestamp = previous.first_timestamp
            self.scan_count = previous.scan_count + 1
        else:
            self.first_timestamp = time.time()
            self.scan_count = 1

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
    def title(self) -> str:
        if self.title_template:
            return self.title_template.format(discovery=self)
        return self.name

    def as_dict(self) -> dict[str, str | list | dict | bool | int | None]:
        return {
            "name": self.name,
            "node": self.node,
            "provider": {"source_type": self.provider.source_type},
            "first_scan": {"timestamp": timestamp(self.first_timestamp)},
            "last_scan": {"session": self.session, "timestamp": timestamp(self.last_timestamp), "throttled": self.throttled},
            "scan_count": self.scan_count,
            "installed_version": self.current_version,
            "latest_version": self.latest_version,
            "title": self.title,
            "release_summary": self.release_summary,
            "release_url": self.release_url,
            "entity_picture_url": self.entity_picture_url,
            "can_update": self.can_update,
            "can_build": self.can_build,
            "can_restart": self.can_restart,
            "device_icon": self.device_icon,
            "update_type": self.update_type,
            "status": self.status,
            "features": self.features,
            "update_policy": self.update_policy,
            "publish_policy": self.publish_policy,
            "update": {"last_attempt": timestamp(self.update_last_attempt), "in_progress": False},
            self.source_type: self.custom,
        }


class ReleaseProvider:
    """Abstract base class for release providers, such as container scanners or package managers API calls"""

    def __init__(
        self, node_cfg: NodeConfig, source_type: str = "base", common_pkg_cfg: dict[str, PackageUpdateInfo] | None = None
    ) -> None:
        self.source_type: str = source_type
        self.discoveries: dict[str, Discovery] = {}
        self.node_cfg: NodeConfig = node_cfg
        self.common_pkg_cfg: dict[str, PackageUpdateInfo] = common_pkg_cfg or {}
        self.log: Any = structlog.get_logger().bind(integration=self.source_type)
        self.stopped = Event()

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
        raise NotImplementedError
        # force recognition as an async generator
        if False:  # type: ignore[unreachable]
            yield 0

    @abstractmethod
    def command(self, discovery_name: str, command: str, on_update_start: Callable, on_update_end: Callable) -> bool:
        """Execute a command on a discovered component"""

    @abstractmethod
    def resolve(self, discovery_name: str) -> Discovery | None:
        """Resolve a discovered component by name"""


class Selection:
    def __init__(self, selector: Selector, value: str | None) -> None:
        self.result: bool = True
        self.matched: str | None = None
        if value is None:
            self.result = selector.include is None
            return
        if selector.exclude is not None:
            self.result = True
            if any(re.search(pat, value) for pat in selector.exclude):
                self.matched = value
                self.result = False
        if selector.include is not None:
            self.result = False
            if any(re.search(pat, value) for pat in selector.include):
                self.matched = value
                self.result = True
