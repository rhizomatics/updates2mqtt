import asyncio
import logging
import signal
import sys
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from typing import Any

import structlog
import structlog.dev

import updates2mqtt
from updates2mqtt.model import Discovery, ReleaseProvider

from .config import Config, PublishPolicy, UpdatePolicy, load_app_config
from .integrations.docker import DockerProvider
from .mqtt import MqttPublisher

log = structlog.get_logger()

CONF_FILE = Path("conf/config.yaml")
UPDATE_INTERVAL = 60 * 60 * 4
# Docker allows 10s after SIGTERM before killing, so leave time for the offline publish
SHUTDOWN_TASK_TIMEOUT = 5
EXIT_SIGTERM = 143
EXIT_SIGINT = 130

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
            log.error(f"Invalid configuration at {CONF_FILE}")
            log.error("Edit config to fix missing or invalid values and restart")
            log.error("Alternately supply correct MQTT_HOST,MQTT_USER,MQTT_PASS environment variables")
            log.error("Exiting app")
            sys.exit(1)
        self.cfg: Config = app_config
        self.self_bounce: Event = Event()

        if not self.cfg.log.json or sys.stderr.isatty():
            # Pretty printing when we run in a terminal session.
            # Automatically prints pretty tracebacks when "rich" is installed
            renderers: list[Any] = [
                structlog.dev.ConsoleRenderer(
                    colors=sys.stderr.isatty(),
                    exception_formatter=(
                        structlog.dev.RichTracebackFormatter() if sys.stderr.isatty() else structlog.dev.plain_traceback
                    ),
                ),
            ]
        else:
            renderers = [
                structlog.processors.dict_tracebacks,
                structlog.processors.JSONRenderer(),
            ]
        structlog.configure(
            cache_logger_on_first_use=True,
            wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, str(self.cfg.log.level))),
            processors=[
                structlog.contextvars.merge_contextvars,
                structlog.processors.add_log_level,
                structlog.processors.StackInfoRenderer(),
                structlog.dev.set_exc_info,
                structlog.processors.TimeStamper(fmt="iso"),
                *renderers,
            ],
        )

        route_stdlib_logging(str(self.cfg.log.level), renderers)
        log.debug("Logging initialized", level=self.cfg.log.level, json=self.cfg.log.json, tty=sys.stderr.isatty())

        self.publisher = MqttPublisher(self.cfg.mqtt, self.cfg.node, self.cfg.homeassistant)

        self.scanners: list[ReleaseProvider] = []
        self.scan_count: int = 0
        self.last_scan: str | None = None
        if self.cfg.docker.enabled:
            self.scanners.append(
                DockerProvider(
                    self.cfg.docker,
                    self.cfg.node,
                    packages=self.cfg.packages,
                    github_cfg=self.cfg.github,
                    self_bounce=self.self_bounce,
                )
            )
        self.stopped = Event()
        self.exit_code: int = 0
        self.main_task: asyncio.Task[Any] | None = None
        self.heartbeat_loop_task: asyncio.Task[None] | None = None
        self.heartbeat_topic = self.cfg.node.healthcheck.topic_template.format(node_name=self.cfg.node.name)

        log.info(
            "App configured",
            node=self.cfg.node.name,
            scan_interval=self.cfg.scan_interval,
            heartbeat_topic=self.heartbeat_topic,
        )

    async def scan(self) -> None:
        session = uuid.uuid4().hex
        for scanner in self.scanners:
            slog = log.bind(source_type=scanner.source_type, session=session)
            if self.stopped.is_set():
                break
            slog.info("Scanning ...")
            async for discovery in scanner.scan(session):
                await self.on_discovery(discovery)
            if self.stopped.is_set():
                slog.debug("Breaking scan loop on stopped event")
                break
            await self.publisher.clean_topics(scanner)
            self.scan_count += 1
            slog.info(f"Scan #{self.scan_count} complete")
        self.last_scan_timestamp = datetime.now(UTC).isoformat()

    async def main_loop(self) -> int:
        """Run until stopped by a signal or a fatal MQTT error, returning the process exit code"""
        log.debug("Starting run loop")
        loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
        self.main_task = asyncio.current_task()
        self.add_signal_handlers(loop)
        try:
            await self.run_loop(loop)
        except asyncio.CancelledError:
            if not self.stopped.is_set():
                raise
            # cancelled by our own stop request, so finish normally with the exit code
            if self.main_task is not None:
                self.main_task.uncancel()
            log.info("Run loop interrupted for shutdown")
        finally:
            await self.shutdown_tasks()
            self.remove_signal_handlers(loop)
        log.debug("Exiting run loop", exit_code=self.exit_code)
        return self.exit_code

    async def run_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        # connection waits for the broker, so keep it off the event loop
        await asyncio.to_thread(self.publisher.start, loop)

        if self.cfg.node.healthcheck.enabled:
            await self.heartbeat()  # initial eager heartbeat
            log.info(f"Setting up heartbeat every {self.cfg.node.healthcheck.interval} seconds to topic {self.heartbeat_topic}")
            self.heartbeat_loop_task = asyncio.create_task(
                repeated_call(self.heartbeat, interval=self.cfg.node.healthcheck.interval), name="heartbeat"
            )

        for scanner in self.scanners:
            await asyncio.to_thread(scanner.initialize)
            self.publisher.subscribe_hass_command(scanner)
            await self.publisher.clean_topics(scanner, initial=True)

        while not self.stopped.is_set() and self.publisher.is_available():
            await self.scan()
            if not self.stopped.is_set() and self.publisher.is_available():
                await asyncio.sleep(self.cfg.scan_interval)
            else:
                log.info("Stop requested, exiting run loop and skipping sleep")

        if not self.publisher.is_available() and not self.stopped.is_set():
            log.error("MQTT fatal connection error - check host,port,user,password in config")
            self.exit_code = 1

    def add_signal_handlers(self, loop: asyncio.AbstractEventLoop) -> None:
        for sig, exit_code in ((signal.SIGTERM, EXIT_SIGTERM), (signal.SIGINT, EXIT_SIGINT)):
            try:
                loop.add_signal_handler(sig, self.request_stop, exit_code)
            except (NotImplementedError, RuntimeError, ValueError):
                # not supported on this platform, or not the main thread
                log.debug("Unable to add signal handler for %s", sig)

    def remove_signal_handlers(self, loop: asyncio.AbstractEventLoop) -> None:
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.remove_signal_handler(sig)
            except (NotImplementedError, RuntimeError, ValueError):
                pass

    async def on_discovery(self, discovery: Discovery) -> None:
        dlog = log.bind(name=discovery.name)
        try:
            if discovery.publish_policy == PublishPolicy.HOMEASSISTANT and self.cfg.homeassistant.discovery.enabled:
                # Switch off MQTT discovery if not Home Assistant enabled
                self.publisher.publish_hass_config(discovery)
            if discovery.publish_policy == PublishPolicy.HOMEASSISTANT:
                self.publisher.publish_hass_state(discovery)
            if discovery.publish_policy in (PublishPolicy.HOMEASSISTANT, PublishPolicy.MQTT):
                self.publisher.publish_discovery(discovery)
            if (
                discovery.update_policy == UpdatePolicy.AUTO
                and discovery.can_update
                and discovery.latest_version != discovery.current_version
            ):
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
            raise
        except Exception:
            dlog.exception("Discovery handling failed")
            raise

    def request_stop(self, exit_code: int = EXIT_SIGTERM) -> None:
        """Signal handler, run on the event loop, so the run loop and tasks can wind down in order"""
        if self.self_bounce.is_set():
            exit_code = 1
            log.info("Self bouncing, overriding exit_code: %s", exit_code)
        else:
            log.info("Shutting down, exit_code: %s", exit_code)
        self.exit_code = exit_code
        if self.stopped.is_set():
            return
        self.stopped.set()
        for scanner in self.scanners:
            scanner.stop()
        if self.main_task is not None and not self.main_task.done():
            # wakes the run loop from a scan or the sleep between scans
            self.main_task.cancel()

    async def shutdown_tasks(self) -> None:
        """Cancel background tasks, e.g. heartbeat and in-flight updates, then mark the node offline"""
        tasks: list[asyncio.Task[Any]] = [*self.publisher.command_tasks]
        for scanner in self.scanners:
            tasks.extend(scanner.background_tasks)
        if self.heartbeat_loop_task is not None:
            tasks.append(self.heartbeat_loop_task)
        tasks = [t for t in tasks if not t.done()]
        log.info(f"Cancelling {len(tasks)} tasks")
        for t in tasks:
            log.debug("Cancelling task", task=t.get_name())
            t.cancel()
        if tasks:
            _done, pending = await asyncio.wait(tasks, timeout=SHUTDOWN_TASK_TIMEOUT)
            if pending:
                log.warning("Tasks still running at shutdown: %s", [t.get_name() for t in pending])
        # waits for the offline availability publish to be acknowledged
        await asyncio.to_thread(self.publisher.stop)
        log.info("Shutdown handling complete")

    async def heartbeat(self) -> None:
        if not self.publisher.is_available():
            return
        heartbeat_stamp: str = datetime.now(UTC).isoformat()
        log.debug("Publishing health check", heartbeat_stamp=heartbeat_stamp)
        self.publisher.publish(
            topic=self.heartbeat_topic,
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


def route_stdlib_logging(level: str, renderers: list[Any], logger_name: str = "updates2mqtt.oci") -> None:
    """Render stdlib logging, as used by the OCI client, the same way as structlog output"""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=[structlog.processors.add_log_level, structlog.processors.TimeStamper(fmt="iso")],
            processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, *renderers],
        )
    )
    stdlib_logger: logging.Logger = logging.getLogger(logger_name)
    stdlib_logger.handlers = [handler]
    stdlib_logger.setLevel(getattr(logging, level, logging.INFO))
    stdlib_logger.propagate = False


async def repeated_call(func: Callable[..., Awaitable[Any]], interval: int = 60, *args: Any, **kwargs: Any) -> None:
    """Run a task periodically until cancelled"""
    while True:
        try:
            await func(*args, **kwargs)
        except Exception:
            log.exception("Periodic task failed")
        await asyncio.sleep(interval)


def run() -> None:
    log.debug(f"Starting updates2mqtt v{updates2mqtt.version}")  # pyright: ignore[reportAttributeAccessIssue]
    app = App()
    exit_code: int = asyncio.run(app.main_loop(), debug=False)
    log.debug("App exited", exit_code=exit_code)
    sys.exit(exit_code)


if __name__ == "__main__":
    run()
