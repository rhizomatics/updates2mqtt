# python
import asyncio
import signal
import time
import types
from collections.abc import AsyncGenerator, Coroutine
from typing import Any, NoReturn
from unittest.mock import Mock, PropertyMock, call

import pytest

from updates2mqtt.app import App, run  # relative import as required
from updates2mqtt.model import Discovery


async def test_scan(
    app_with_mocked_external_dependencies: App,
    mock_discoveries: list[Discovery],
    mock_discovery_generator: AsyncGenerator[Discovery],
    monkeypatch,  # noqa: ANN001
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
    monkeypatch,  # noqa: ANN001
) -> None:
    uut: App = app_with_mocked_external_dependencies
    monkeypatch.setattr(uut.scanners[0], "scan", mock_discovery_generator)
    start_time = time.time()
    monkeypatch.setattr(uut.publisher, "is_available", lambda: time.time() > start_time + 3)

    with pytest.raises(SystemExit):
        await uut.main_loop()
    uut.publisher.assert_has_calls(  # type: ignore[attr-defined]
        [
            call.start(),
            call.subscribe_hass_command(uut.scanners[0]),
            call.clean_topics(uut.scanners[0], initial=True),
            call.stop(),
        ]
    )  # pyright: ignore[reportAttributeAccessIssue]


class DummyApp:
    """Dummy App to replace updates2mqtt.app.App during tests.

    Records the created instance on DummyApp.instance for assertions.
    """

    instance = None

    def __init__(self) -> None:
        DummyApp.instance = self
        self.run_called = False
        self.shutdown_called = False

    async def main_loop(self) -> None:
        # an async method to mirror the real App.run signature
        self.run_called = True

    def shutdown(self, *args: Any, **kwargs: Any) -> None:  # noqa: ARG002
        self.shutdown_called = True


def test_run_sets_signal_and_calls_asyncio_run(monkeypatch) -> None:  # noqa: ANN001
    calls: dict[str, Any] = {}

    # Replace signal.signal so we capture its arguments
    def fake_signal(sig: int, handler: types.MethodType) -> None:
        calls["sig"] = sig
        calls["handler"] = handler

    monkeypatch.setattr(signal, "signal", fake_signal)

    # Patch the App class in the updates2mqtt.app module to DummyApp
    import updates2mqtt.app as app_module

    monkeypatch.setattr(app_module, "App", DummyApp)

    # Patch asyncio.run to record that it was called with a coroutine and debug flag
    def fake_asyncio_run(coro: Coroutine, debug: bool = False) -> None:
        calls["coro"] = coro
        calls["debug"] = debug
        return

    monkeypatch.setattr(asyncio, "run", fake_asyncio_run)

    # Execute the run function under test
    run()

    # Assertions:
    # - signal.signal was called with SIGTERM and the DummyApp.instance.shutdown bound method
    assert calls.get("sig") == signal.SIGTERM
    assert DummyApp.instance is not None
    assert calls.get("handler") == DummyApp.instance.shutdown
    # debug flag forwarded as False in run()
    assert calls.get("debug") is False
    # - asyncio.run was called with a coroutine object (the result of DummyApp.instance.run())
    coro = calls.get("coro")
    assert isinstance(coro, types.CoroutineType)


def test_run_handles_asyncio_cancellederror(monkeypatch) -> None:  # noqa: ANN001
    # Ensure App is replaced so run() will create DummyApp without side effects
    import updates2mqtt.app as app_module

    monkeypatch.setattr(app_module, "App", DummyApp)

    # Patch signal.signal to a noop to avoid altering test process handlers
    monkeypatch.setattr(signal, "signal", lambda *args, **kwargs: None)  # noqa: ARG005

    # Patch asyncio.run to raise CancelledError to exercise the except branch
    def raising_asyncio_run(_coro: Coroutine, debug: bool = False) -> NoReturn:  # noqa: ARG001
        raise asyncio.CancelledError()

    monkeypatch.setattr(asyncio, "run", raising_asyncio_run)

    # Call run(); should not raise CancelledError (handled inside run)
    run()

    # If we reached here, the CancelledError was handled; also ensure DummyApp was instantiated
    assert DummyApp.instance is not None


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


async def test_shutdown_with_self_bounce_uses_exit_code_1(
    app_with_mocked_external_dependencies: App,
) -> None:
    uut = app_with_mocked_external_dependencies
    uut.self_bounce.set()

    with pytest.raises(SystemExit) as exc_info:
        uut.shutdown()

    assert exc_info.value.code == 1
