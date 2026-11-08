"""Transport behaviour that needs no sockets: httpx mock transports, client ownership and library fallback"""

import importlib.util
from typing import Any
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from updates2mqtt.oci import HttpRequest, TransportError
from updates2mqtt.oci.transports import default_async_transport, default_transport
from updates2mqtt.oci.transports.httpx_transport import AsyncHttpxTransport, HttpxTransport, request_kwargs


def oci_request(form: dict[str, str] | None = None) -> HttpRequest:
    return HttpRequest(
        method="POST" if form else "GET",
        url="https://registry.test/v2/",
        headers={"Accept": "application/json"},
        form=form,
        kind="manifest",
        registry="registry.test",
    )


def test_request_kwargs_includes_body_and_extensions() -> None:
    kwargs = request_kwargs(oci_request({"a": "b"}))
    assert kwargs["content"] == b"a=b"
    assert kwargs["extensions"]["oci_kind"] == "manifest"
    assert kwargs["extensions"]["oci_registry"] == "registry.test"
    assert "content" not in request_kwargs(oci_request())


def echo(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, headers={"X-Echo": request.headers.get("X-Prepared", "")}, content=request.content)


def prepared(request: HttpRequest, kwargs: dict[str, Any]) -> None:
    kwargs["headers"]["X-Prepared"] = request.kind


def test_sync_send_prepare_and_close() -> None:
    client = httpx.Client(transport=httpx.MockTransport(echo))
    uut = HttpxTransport(client, prepare=prepared)
    response = uut.send(oci_request({"x": "1"}))
    assert response.status_code == 200
    assert response.content == b"x=1"
    assert response.headers.get("x-echo") == "manifest"
    uut.close()
    # caller owns the injected client
    assert not client.is_closed

    owned = HttpxTransport()
    owned.close()
    assert owned.client.is_closed


def test_sync_send_wraps_http_errors() -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    uut = HttpxTransport(httpx.Client(transport=httpx.MockTransport(fail)))
    with pytest.raises(TransportError, match="refused"):
        uut.send(oci_request())


async def test_async_send_prepare_and_close() -> None:
    client = httpx.AsyncClient(transport=httpx.MockTransport(echo))
    uut = AsyncHttpxTransport(client, prepare=prepared)
    response = await uut.send(oci_request({"y": "2"}))
    assert response.content == b"y=2"
    assert response.headers.get("x-echo") == "manifest"
    await uut.aclose()
    assert not client.is_closed
    await client.aclose()

    owned = AsyncHttpxTransport()
    await owned.aclose()
    assert owned.client.is_closed


async def test_async_send_wraps_http_errors() -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    uut = AsyncHttpxTransport(httpx.AsyncClient(transport=httpx.MockTransport(fail)))
    with pytest.raises(TransportError, match="slow"):
        await uut.send(oci_request())


def only_libraries(monkeypatch: pytest.MonkeyPatch, *available: str) -> None:
    real_find_spec = importlib.util.find_spec

    def find_spec(name: str, *args: Any, **kwargs: Any) -> Any:
        if name in ("niquests", "httpx"):
            return real_find_spec(name) if name in available else None
        return real_find_spec(name, *args, **kwargs)

    monkeypatch.setattr(importlib.util, "find_spec", find_spec)


def test_default_transports_fall_back_to_httpx(monkeypatch: pytest.MonkeyPatch) -> None:
    only_libraries(monkeypatch, "httpx")
    assert isinstance(default_transport(), HttpxTransport)
    assert isinstance(default_async_transport(), AsyncHttpxTransport)


def test_default_transports_need_a_library(monkeypatch: pytest.MonkeyPatch) -> None:
    only_libraries(monkeypatch)
    with pytest.raises(ImportError, match="niquests or httpx"):
        default_transport()
    with pytest.raises(ImportError, match="niquests or httpx"):
        default_async_transport()


def test_niquests_close_only_owned_sessions() -> None:
    import niquests

    from updates2mqtt.oci.transports.niquests_transport import NiquestsTransport

    session = Mock(spec=niquests.Session)
    NiquestsTransport(session).close()
    session.close.assert_not_called()
    owned = NiquestsTransport()
    owned.session = Mock(spec=niquests.Session)
    owned.close()
    owned.session.close.assert_called_once()


async def test_async_niquests_close_only_owned_sessions() -> None:
    import niquests

    from updates2mqtt.oci.transports.niquests_transport import AsyncNiquestsTransport

    session = AsyncMock(spec=niquests.AsyncSession)
    await AsyncNiquestsTransport(session).aclose()
    session.close.assert_not_awaited()
    owned = AsyncNiquestsTransport()
    await owned.session.close()
    owned.session = AsyncMock(spec=niquests.AsyncSession)
    await owned.aclose()
    owned.session.close.assert_awaited_once()
