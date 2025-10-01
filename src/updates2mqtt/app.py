import asyncio
import logging
import sys
import time
import uuid
from pathlib import Path
import signal
from threading import Event
import structlog

from updates2mqtt.model import Discovery, ReleaseProvider

from .config import Config, load_app_config, load_package_info
from .integrations.docker import DockerProvider
from .mqtt import MqttClient

log = structlog.get_logger()

CONF_FILE = Path("conf/config.yaml")
PKG_INFO_FILE = Path("./common_packages.yaml")
UPDATE_INTERVAL = 60 * 60 * 4

# #TODO:
#  - Set install in progress
#  - Support apt
#  - Retry on registry fetch fail
#  - Fetcher in subproc or thread
#  - Clear command message after install
#  - use git hash as alt to img ref for builds, or daily builds


class App:
    def __init__(self) -> None:
        app_config: Config | None = load_app_config(CONF_FILE)
        if app_config is None:
            log.error("Invalid configuration, exiting")
            sys.exit(1)
        self.cfg: Config = app_config
        logging.basicConfig(
            format="%(message)s",
            stream=sys.stdout,
            level=self.cfg.log.level,
        )
        structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, self.cfg.log.level)))
        log.debug("Logging initialized", level=self.cfg.log.level)
        self.common_pkg = load_package_info(PKG_INFO_FILE)

        self.publisher = MqttClient(self.cfg.mqtt, self.cfg.node, self.cfg.homeassistant)

        self.scanners: list[ReleaseProvider] = []
        self.scan_count: int = 0
        if self.cfg.docker.enabled:
            self.scanners.append(DockerProvider(self.cfg.docker, self.common_pkg))
        self.running = Event()
        log.info(
            "App configured",
            node=self.cfg.node.name,
            scan_interval=self.cfg.scan_interval,
        )

    async def scan(self) -> None:
        session = uuid.uuid4().hex
        for scanner in self.scanners:
            log.info("Cleaning topics before scan", source_type=scanner.source_type)
            if self.scan_count == 0:
                await self.publisher.clean_topics(scanner, None, force=True)
            log.info("Scanning", source=scanner.source_type, session=session)
            async for discovery in scanner.scan(session):  # type: ignore[attr-defined]
                async with asyncio.TaskGroup() as tg:
                    tg.create_task(self.on_discovery(discovery))
            await self.publisher.clean_topics(scanner, session, force=False)
            self.scan_count += 1
            log.info("Scan complete", source_type=scanner.source_type)

    async def run(self) -> None:
        self.publisher.start()
        for scanner in self.scanners:
            self.publisher.subscribe_hass_command(scanner)

        while self.running.is_set():
            await self.scan()
            if self.running.is_set():
                await asyncio.sleep(self.cfg.scan_interval)
        log.debug("Exiting run loop")

    async def on_discovery(self, discovery: Discovery) -> None:
        dlog = log.bind(name=discovery.name)
        if self.cfg.homeassistant.discovery.enabled:
            self.publisher.publish_hass_config(discovery)

        self.publisher.publish_hass_state(discovery)
        if discovery.update_policy == "Auto":
            # TODO: review auto update, trigger by version, use update interval as throttle
            elapsed: float = time.time() - discovery.update_last_attempt if discovery.update_last_attempt is not None else -1
            if elapsed == -1 or elapsed > UPDATE_INTERVAL:
                dlog.info(
                    "Initiate auto update (last:%s, elapsed:%s, max:%s)",
                    discovery.update_last_attempt,
                    elapsed,
                    UPDATE_INTERVAL,
                )
                self.publisher.local_message(discovery, "install")
            else:
                dlog.info("Skipping auto update")

    def shutdown(self) -> None:
        log.info("Shutting down")
        self.running.clear()
        self.publisher.stop()
        log.info("Shutdown complete")


if __name__ == "__main__":
    app = App()
    asyncio.run(app.run())
