import asyncio
import logging
import sys
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from typing import Any

import structlog

import updates2mqtt
from updates2mqtt.model import Discovery, ReleaseProvider

from .config import Config, PackageUpdateInfo, load_app_config, load_package_info
from .integrations.docker import DockerProvider
from .mqtt import MqttPublisher

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
        self.startup_timestamp: str = datetime.now(UTC).isoformat()
        self.last_scan_timestamp: str | None = None
        app_config: Config | None = load_app_config(CONF_FILE)
        if app_config is None:
            log.error(f"Invalid configuration at {CONF_FILE}, edit config to fix missing or invalid values and restart")
            log.error("Exiting app")
            sys.exit(1)
        self.cfg: Config = app_config

        structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, str(self.cfg.log.level))))
        log.debug("Logging initialized", level=self.cfg.log.level)
        self.common_pkg: dict[str, PackageUpdateInfo] = load_package_info(PKG_INFO_FILE)

        self.publisher = MqttPublisher(self.cfg.mqtt, self.cfg.node, self.cfg.homeassistant)

        self.scanners: list[ReleaseProvider] = []
        self.scan_count: int = 0
        self.last_scan: str | None = None
        if self.cfg.docker.enabled:
            self.scanners.append(DockerProvider(self.cfg.docker, self.common_pkg, self.cfg.node))
        self.stopped = Event()
        self.healthcheck_topic = self.cfg.node.healthcheck.topic_template.format(node_name=self.cfg.node.name)

        log.info(
            "App configured",
            node=self.cfg.node.name,
            scan_interval=self.cfg.scan_interval,
            healthcheck_topic=self.healthcheck_topic,
        )

    async def scan(self) -> None:
        session = uuid.uuid4().hex
        for scanner in self.scanners:
            slog = log.bind(source_type=scanner.source_type, session=session)
            slog.info("Cleaning topics before scan")
            if self.scan_count == 0:
                await self.publisher.clean_topics(scanner, None, force=True)
            if self.stopped.is_set():
                break
            slog.info("Scanning ...")
            async with asyncio.TaskGroup() as tg:
                # xtype: ignore[attr-defined]
                async for discovery in scanner.scan(session):
                    tg.create_task(self.on_discovery(discovery), name=f"discovery-{discovery.name}")
            if self.stopped.is_set():
                slog.debug("Breaking scan loop on stopped event")
                break
            await self.publisher.clean_topics(scanner, session, force=False)
            self.scan_count += 1
            slog.info(f"Scan #{self.scan_count} complete")
        self.last_scan_timestamp = datetime.now(UTC).isoformat()

    async def main_loop(self) -> None:
        log.debug("Starting run loop")
        self.publisher.start()

        if self.cfg.node.healthcheck.enabled:
            await self.healthcheck()  # initial eager healthcheck
            log.info(
                f"Setting up healthcheck every {self.cfg.node.healthcheck.interval} seconds to topic {self.healthcheck_topic}"
            )
            self.healthcheck_loop_task = asyncio.create_task(
                repeated_call(self.healthcheck, interval=self.cfg.node.healthcheck.interval), name="healthcheck"
            )

        for scanner in self.scanners:
            self.publisher.subscribe_hass_command(scanner)

        while not self.stopped.is_set() and self.publisher.is_available():
            await self.scan()
            if not self.stopped.is_set() and self.publisher.is_available():
                await asyncio.sleep(self.cfg.scan_interval)
            else:
                log.info("Stop requested, exiting run loop and skipping sleep")

        if not self.publisher.is_available():
            log.error("MQTT fatal connection error - check host,port,user,password in config")
            self.shutdown(exit_code=1)

        log.debug("Exiting run loop")

    async def on_discovery(self, discovery: Discovery) -> None:
        dlog = log.bind(name=discovery.name)
        try:
            if self.cfg.homeassistant.discovery.enabled:
                self.publisher.publish_hass_config(discovery)

            self.publisher.publish_hass_state(discovery)
            if discovery.update_policy == "Auto":
                # TODO: review auto update, trigger by version, use update interval as throttle
                elapsed: float = (
                    time.time() - discovery.update_last_attempt if discovery.update_last_attempt is not None else -1
                )
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
        except asyncio.CancelledError:
            dlog.info("Discovery handling cancelled")
        except Exception:
            dlog.exception("Discovery handling failed")
            raise

    async def interrupt_tasks(self) -> None:
        running_tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        log.info(f"Cancelling {len(running_tasks)} tasks")
        for t in running_tasks:
            log.debug("Cancelling task", task=t.get_name())
            if t.get_name() == "healthcheck" or t.get_name().startswith("discovery-"):
                t.cancel()
        await asyncio.gather(*running_tasks, return_exceptions=True)
        log.debug("Cancellation task completed")

    def shutdown(self, *args, exit_code: int = 143) -> None:  # noqa: ANN002, ARG002
        log.info("Shutting down, exit_code: %s", exit_code)
        self.stopped.set()
        for scanner in self.scanners:
            scanner.stop()
        interrupt_task = asyncio.get_event_loop().create_task(
            self.interrupt_tasks(),
            eager_start=True,  # type: ignore[call-arg] # pyright: ignore[reportCallIssue]
            name="interrupt",
        )
        for t in asyncio.all_tasks():
            log.debug("Tasks waiting = %s", t)
        self.publisher.stop()
        log.debug("Interrupt: %s", interrupt_task.done())
        log.info("Shutdown handling complete")
        sys.exit(exit_code)  # SIGTERM Graceful Exit = 143

    async def healthcheck(self) -> None:
        if not self.publisher.is_available():
            return
        heartbeat_stamp: str = datetime.now(UTC).isoformat()
        log.debug("Publishing health check", heartbeat_stamp=heartbeat_stamp)
        self.publisher.publish(
            topic=self.healthcheck_topic,
            payload={
                "version": updates2mqtt.version,  # pyright: ignore[reportAttributeAccessIssue]
                "node": self.cfg.node.name,
                "heartbeat_raw": time.time(),
                "heartbeat_stamp": heartbeat_stamp,
                "startup_stamp": self.startup_timestamp,
                "last_scan_stamp": self.last_scan_timestamp,
                "scan_count": self.scan_count,
            },
        )


async def repeated_call(func: Callable, interval: int = 60, *args: Any, **kwargs: Any) -> None:
    # run a task periodically indefinitely
    while True:
        try:
            await func(*args, **kwargs)
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            log.debug("Periodic task cancelled", func=func)
        except Exception:
            log.exception("Periodic task failed")


def run() -> None:
    import asyncio
    import signal

    from .app import App

    # pyright: ignore[reportAttributeAccessIssue]
    log.debug(f"Starting updates2mqtt v{updates2mqtt.version}")  # pyright: ignore[reportAttributeAccessIssue]
    app = App()

    signal.signal(signal.SIGTERM, app.shutdown)
    try:
        asyncio.run(app.main_loop(), debug=False)
        log.debug("App exited gracefully")
    except asyncio.CancelledError:
        log.debug("App exited on cancelled task")


if __name__ == "__main__":
    run()
