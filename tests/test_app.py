# python
import asyncio
import os
import signal
import sys
import time
from collections.abc import AsyncGenerator
from unittest.mock import ANY, Mock, PropertyMock, call

import pytest

from updates2mqtt.app import EXIT_SIGTERM, App, repeated_call, run
from updates2mqtt.model import Discovery


async def test_scan(
    app_with_mocked_external_dependencies: App,
    mock_discoveries: list[Discovery],
    mock_discovery_generator: AsyncGenerator[Discovery],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uut: App = app_with_mocked_external_dependencies
    monkeypatch.setattr(uut.scanners[0], "scan", mock_discovery_generator)
    await uut.scan()
    uut.publisher.clean_topics.assert_has_calls(  # type: ignore[attr-defined]
        [call(uut.scanners[0])]
    )
    uut.publisher.publish_hass_state.assert_has_calls([call(d) for d in mock_discoveries])  # type: ignore[attr-defined]


async def test_main_loop(
    app_with_mocked_external_dependencies: App,
    mock_discovery_generator: AsyncGenerator[Discovery],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uut: App = app_with_mocked_external_dependencies
    monkeypatch.setattr(uut.scanners[0], "scan", mock_discovery_generator)
    start_time = time.time()
    monkeypatch.setattr(uut.publisher, "is_available", lambda: time.time() > start_time + 3)

    # MQTT unavailable ends the loop as a fatal error
    assert await uut.main_loop() == 1
    uut.publisher.assert_has_calls(  # type: ignore[attr-defined]
        [
            call.start(ANY),
            call.subscribe_hass_command(uut.scanners[0]),
            call.clean_topics(uut.scanners[0], initial=True),
            call.stop(),
        ]
    )  # pyright: ignore[reportAttributeAccessIssue]


async def test_main_loop_stop_wakes_sleep_between_scans(
    app_with_mocked_external_dependencies: App,
    mock_discovery_generator: AsyncGenerator[Discovery],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uut: App = app_with_mocked_external_dependencies
    uut.cfg.scan_interval = 3600
    monkeypatch.setattr(uut.scanners[0], "scan", mock_discovery_generator)
    uut.publisher.is_available.return_value = True  # type: ignore[attr-defined]

    running = asyncio.create_task(uut.main_loop())
    await asyncio.sleep(0.2)
    uut.request_stop()
    assert await asyncio.wait_for(running, timeout=5) == EXIT_SIGTERM
    assert uut.stopped.is_set()
    uut.scanners[0].stop.assert_called_once()  # type: ignore[attr-defined]
    uut.publisher.stop.assert_called_once()  # type: ignore[attr-defined]


async def test_main_loop_stops_on_sigterm(
    app_with_mocked_external_dependencies: App,
    mock_discovery_generator: AsyncGenerator[Discovery],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uut: App = app_with_mocked_external_dependencies
    uut.cfg.scan_interval = 3600
    monkeypatch.setattr(uut.scanners[0], "scan", mock_discovery_generator)
    uut.publisher.is_available.return_value = True  # type: ignore[attr-defined]

    running = asyncio.create_task(uut.main_loop())
    await asyncio.sleep(0.2)
    os.kill(os.getpid(), signal.SIGTERM)
    assert await asyncio.wait_for(running, timeout=5) == EXIT_SIGTERM
    # handlers removed again, so later signals get default handling
    assert not asyncio.get_running_loop().remove_signal_handler(signal.SIGTERM)


async def test_shutdown_tasks_cancels_background_work(app_with_mocked_external_dependencies: App) -> None:
    uut: App = app_with_mocked_external_dependencies
    command = asyncio.create_task(asyncio.sleep(3600))
    uut.publisher.command_tasks.add(command)
    background = asyncio.create_task(asyncio.sleep(3600))
    uut.scanners[0].background_tasks.add(background)
    unrelated = asyncio.create_task(asyncio.sleep(3600))
    await uut.shutdown_tasks()
    assert command.cancelled()
    assert background.cancelled()
    # only tasks the app owns are cancelled
    assert not unrelated.done()
    unrelated.cancel()
    uut.publisher.stop.assert_called_once()  # type: ignore[attr-defined]


def test_run_exits_with_main_loop_code(monkeypatch: pytest.MonkeyPatch) -> None:
    import updates2mqtt.app as app_module

    class DummyApp:
        async def main_loop(self) -> int:
            return 143

    monkeypatch.setattr(app_module, "App", DummyApp)
    with pytest.raises(SystemExit) as exc_info:
        run()
    assert exc_info.value.code == 143


async def test_repeated_call_survives_errors_and_cancels() -> None:
    calls: int = 0

    async def flaky() -> None:
        nonlocal calls
        calls += 1
        raise RuntimeError("boom")

    task = asyncio.create_task(repeated_call(flaky, interval=0))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert calls > 1


# === on_discovery policy branches ===


async def test_on_discovery_mqtt_policy(
    app_with_mocked_external_dependencies: App,
    mock_discoveries: list[Discovery],
) -> None:
    """MQTT publish policy skips hass-specific publishes but calls publish_discovery."""
    from updates2mqtt.config import PublishPolicy

    uut = app_with_mocked_external_dependencies
    discovery = mock_discoveries[0]
    discovery.publish_policy = PublishPolicy.MQTT

    await uut.on_discovery(discovery)

    uut.publisher.publish_hass_config.assert_not_called()  # type: ignore[attr-defined]
    uut.publisher.publish_hass_state.assert_not_called()  # type: ignore[attr-defined]
    uut.publisher.publish_discovery.assert_called_once_with(discovery)  # type: ignore[attr-defined]


def _auto_update_discovery(update_last_attempt: float | None) -> Mock:
    """Build a mock Discovery configured for AUTO update testing."""
    from updates2mqtt.config import PublishPolicy, UpdatePolicy

    disc = Mock(spec=Discovery)
    disc.name = "testpkg"
    disc.publish_policy = PublishPolicy.HOMEASSISTANT
    disc.update_policy = UpdatePolicy.AUTO
    type(disc).can_update = PropertyMock(return_value=True)
    disc.latest_version = "2.0.0"
    disc.current_version = "1.0.0"
    disc.update_last_attempt = update_last_attempt
    return disc


async def test_on_discovery_auto_update_triggered(
    app_with_mocked_external_dependencies: App,
) -> None:
    """AUTO update policy with a version diff and no prior attempt triggers local_message."""
    uut = app_with_mocked_external_dependencies
    discovery = _auto_update_discovery(update_last_attempt=None)

    await uut.on_discovery(discovery)

    uut.publisher.local_message.assert_called_once_with(discovery, "install")  # type: ignore[attr-defined]


async def test_on_discovery_auto_update_skipped_when_recent(
    app_with_mocked_external_dependencies: App,
) -> None:
    """AUTO update skips install when last attempt was recent (< UPDATE_INTERVAL)."""
    uut = app_with_mocked_external_dependencies
    discovery = _auto_update_discovery(update_last_attempt=time.time())

    await uut.on_discovery(discovery)

    uut.publisher.local_message.assert_not_called()  # type: ignore[attr-defined]


# === heartbeat ===


async def test_heartbeat_publishes_when_publisher_available(
    app_with_mocked_external_dependencies: App,
) -> None:
    uut = app_with_mocked_external_dependencies
    uut.publisher.is_available.return_value = True  # type: ignore[attr-defined]

    await uut.heartbeat()

    uut.publisher.publish.assert_called_once()  # type: ignore[attr-defined]
    payload = uut.publisher.publish.call_args.kwargs["payload"]  # type: ignore[attr-defined]
    assert "heartbeat_raw" in payload


async def test_heartbeat_skips_when_publisher_unavailable(
    app_with_mocked_external_dependencies: App,
) -> None:
    uut = app_with_mocked_external_dependencies
    uut.publisher.is_available.return_value = False  # type: ignore[attr-defined]

    await uut.heartbeat()

    uut.publisher.publish.assert_not_called()  # type: ignore[attr-defined]


# === shutdown ===


async def test_request_stop_with_self_bounce_uses_exit_code_1(
    app_with_mocked_external_dependencies: App,
) -> None:
    uut = app_with_mocked_external_dependencies
    uut.self_bounce.set()

    uut.request_stop()

    assert uut.exit_code == 1
    assert uut.stopped.is_set()


async def test_request_stop_default_exit_code(app_with_mocked_external_dependencies: App) -> None:
    uut = app_with_mocked_external_dependencies
    uut.request_stop()
    assert uut.exit_code == EXIT_SIGTERM


def test_route_stdlib_logging(capsys: pytest.CaptureFixture[str]) -> None:
    import logging

    import structlog

    from updates2mqtt.app import route_stdlib_logging

    route_stdlib_logging("DEBUG", [structlog.processors.JSONRenderer()], logger_name="updates2mqtt.test_routing")
    logging.getLogger("updates2mqtt.test_routing.child").debug("hello %s", "registry")
    line = capsys.readouterr().out.strip().splitlines()[-1]
    assert '"event": "hello registry"' in line
    assert '"level": "debug"' in line


# === startup and edge paths ===


def test_app_exits_on_invalid_config(monkeypatch: pytest.MonkeyPatch) -> None:
    import updates2mqtt.app as app_module

    monkeypatch.setattr(app_module, "load_app_config", lambda *_args, **_kwargs: None)
    with pytest.raises(SystemExit) as exc_info:
        App()
    assert exc_info.value.code == 1


def test_app_json_logging_when_not_a_terminal(
    monkeypatch: pytest.MonkeyPatch, mock_provider_class: type, mock_publisher_class: type
) -> None:
    import structlog
    from omegaconf import OmegaConf

    import updates2mqtt.app as app_module
    from updates2mqtt.config import Config

    cfg = OmegaConf.structured(Config)
    cfg.log.json = True
    cfg.docker.enabled = False
    monkeypatch.setattr(app_module, "load_app_config", lambda *_args, **_kwargs: cfg)
    monkeypatch.setattr(app_module, "MqttPublisher", mock_publisher_class)
    monkeypatch.setattr(sys.stderr, "isatty", lambda: False)
    try:
        uut = App()
        assert uut.scanners == []
        processors = structlog.get_config()["processors"]
        assert any(isinstance(p, structlog.processors.JSONRenderer) for p in processors)
    finally:
        structlog.reset_defaults()


def test_main_module_runs_app(monkeypatch: pytest.MonkeyPatch) -> None:
    import runpy

    import updates2mqtt.app as app_module

    ran = Mock()
    monkeypatch.setattr(app_module, "run", ran)
    runpy.run_module("updates2mqtt", run_name="__main__")
    ran.assert_called_once()
    # importing it doesn't start the app
    runpy.run_module("updates2mqtt.__main__", run_name="updates2mqtt.__main__")
    ran.assert_called_once()


async def test_scan_skipped_when_already_stopped(app_with_mocked_external_dependencies: App) -> None:
    uut = app_with_mocked_external_dependencies
    uut.stopped.set()
    await uut.scan()
    uut.scanners[0].scan.assert_not_called()  # type: ignore[attr-defined]
    assert uut.scan_count == 0
    assert uut.last_scan_timestamp is not None


async def test_scan_stops_mid_scan_without_cleaning(
    app_with_mocked_external_dependencies: App, monkeypatch: pytest.MonkeyPatch, mock_discoveries: list[Discovery]
) -> None:
    uut = app_with_mocked_external_dependencies

    async def stop_during_scan(*_args: object) -> AsyncGenerator[Discovery]:
        yield mock_discoveries[0]
        uut.stopped.set()

    monkeypatch.setattr(uut.scanners[0], "scan", stop_during_scan)
    await uut.scan()
    uut.publisher.clean_topics.assert_not_called()  # type: ignore[attr-defined]
    assert uut.scan_count == 0


async def test_main_loop_external_cancel_propagates(
    app_with_mocked_external_dependencies: App, monkeypatch: pytest.MonkeyPatch
) -> None:
    uut = app_with_mocked_external_dependencies

    async def hang(_loop: asyncio.AbstractEventLoop) -> None:
        await asyncio.sleep(3600)

    monkeypatch.setattr(uut, "run_loop", hang)
    running = asyncio.create_task(uut.main_loop())
    await asyncio.sleep(0.05)
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running
    # still shuts down cleanly
    uut.publisher.stop.assert_called_once()  # type: ignore[attr-defined]


async def test_run_loop_skips_sleep_when_stopped_during_scan(
    app_with_mocked_external_dependencies: App, monkeypatch: pytest.MonkeyPatch
) -> None:
    uut = app_with_mocked_external_dependencies
    uut.cfg.node.healthcheck.enabled = False
    uut.cfg.scan_interval = 3600
    uut.publisher.is_available.return_value = True  # type: ignore[attr-defined]

    async def scan_then_stop() -> None:
        uut.stopped.set()

    monkeypatch.setattr(uut, "scan", scan_then_stop)
    await asyncio.wait_for(uut.run_loop(asyncio.get_running_loop()), timeout=5)
    assert uut.exit_code == 0


def test_signal_handlers_tolerate_unsupported_loop(app_with_mocked_external_dependencies: App) -> None:
    loop = Mock()
    loop.add_signal_handler.side_effect = NotImplementedError
    loop.remove_signal_handler.side_effect = RuntimeError
    app_with_mocked_external_dependencies.add_signal_handlers(loop)
    app_with_mocked_external_dependencies.remove_signal_handlers(loop)
    assert loop.add_signal_handler.call_count == 2
    assert loop.remove_signal_handler.call_count == 2


@pytest.mark.parametrize("error", [RuntimeError("publish failed"), asyncio.CancelledError()])
async def test_on_discovery_reraises_errors(
    app_with_mocked_external_dependencies: App, mock_discoveries: list[Discovery], error: BaseException
) -> None:
    uut = app_with_mocked_external_dependencies
    uut.publisher.publish_hass_state.side_effect = error  # type: ignore[attr-defined]
    with pytest.raises(type(error)):
        await uut.on_discovery(mock_discoveries[0])


async def test_request_stop_is_idempotent(app_with_mocked_external_dependencies: App) -> None:
    uut = app_with_mocked_external_dependencies
    uut.request_stop()
    uut.request_stop(exit_code=130)
    assert uut.exit_code == 130
    uut.scanners[0].stop.assert_called_once()  # type: ignore[attr-defined]


async def test_shutdown_tasks_reports_tasks_ignoring_cancel(
    app_with_mocked_external_dependencies: App, monkeypatch: pytest.MonkeyPatch
) -> None:
    import updates2mqtt.app as app_module

    uut = app_with_mocked_external_dependencies
    monkeypatch.setattr(app_module, "SHUTDOWN_TASK_TIMEOUT", 0.05)
    release = asyncio.Event()

    async def stubborn() -> None:
        while not release.is_set():
            try:
                await release.wait()
            except asyncio.CancelledError:
                continue

    task = asyncio.create_task(stubborn(), name="stubborn")
    uut.scanners[0].background_tasks.add(task)
    await asyncio.sleep(0)
    await uut.shutdown_tasks()
    assert not task.done()
    release.set()
    await task
