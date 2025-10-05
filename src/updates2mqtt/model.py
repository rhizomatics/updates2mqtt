from abc import abstractmethod
from collections.abc import AsyncGenerator, Callable
from threading import Event
from typing import Any

import structlog


class Discovery:
    """Discovered component from a scan"""

    def __init__(
        self,
        provider: "ReleaseProvider",
        name: str,
        session: str,
        entity_picture_url: str | None = None,
        current_version: str | None = None,
        latest_version: str | None = None,
        can_update: bool = False,
        can_build: bool = False,
        can_restart: bool = False,
        status: str = "on",
        update_policy: str | None = None,
        update_last_attempt: float | None = None,
        release_url: str | None = None,
        release_summary: str | None = None,
        title_template: str = "Update for {name} on {node}",
        device_icon: str | None = None,
        custom: dict[str, Any] | None = None,
        features: list[str] | None = None,
    ) -> None:
        self.provider: ReleaseProvider = provider
        self.source_type: str = provider.source_type
        self.session: str = session
        self.name: str = name
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
        self.status: str = status
        self.update_policy: str | None = update_policy
        self.update_last_attempt: float | None = update_last_attempt
        self.custom: dict[str, Any] = custom or {}
        self.features: list[str] = features or []

    def __repr__(self) -> str:
        """Build a custom string representation"""
        return f"Discovery('{self.name}','{self.source_type}',current={self.current_version},latest={self.latest_version})"


class ReleaseProvider:
    """Abstract base class for release providers, such as container scanners or package managers API calls"""

    def __init__(self, source_type: str = "base") -> None:
        self.source_type: str = source_type
        self.discoveries: dict[str, Discovery] = {}
        self.log: Any = structlog.get_logger().bind(integration=self.source_type)
        self.stopped = Event()

    def stop(self) -> None:
        """Stop any loops or background tasks"""
        self.log.info("Asking release provider to stop", source_type=self.source_type)
        self.stopped.set()

    @abstractmethod
    def update(self, discovery: Discovery) -> bool:
        """Attempt to update the component version"""

    @abstractmethod
    def rescan(self, discovery: Discovery) -> Discovery | None:
        """Rescan a previously discovered component"""

    @abstractmethod
    async def scan(self, session: str) -> AsyncGenerator[Discovery]:
        """Scan for components to monitor"""

    def hass_config_format(self, discovery: Discovery) -> dict:
        _ = discovery
        return {}

    def hass_state_format(self, discovery: Discovery) -> dict:
        _ = discovery
        return {}

    @abstractmethod
    def command(self, discovery_name: str, command: str, on_update_start: Callable, on_update_end: Callable) -> bool:
        """Execute a command on a discovered component"""

    @abstractmethod
    def resolve(self, discovery_name: str) -> Discovery | None:
        """Resolve a discovered component by name"""
