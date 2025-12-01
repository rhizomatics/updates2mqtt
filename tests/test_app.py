# python
import asyncio
import signal
import time
import types
from collections.abc import AsyncGenerator, Coroutine
from typing import Any, NoReturn
from unittest.mock import ANY, call

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
        [call(uut.scanners[0], None, force=True), call(uut.scanners[0], ANY, force=False)]
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
