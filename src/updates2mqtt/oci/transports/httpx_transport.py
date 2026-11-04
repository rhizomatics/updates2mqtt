"""httpx transport, takes a client so it can be one with caching, e.g. hishel's"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx

from ..errors import TransportError
from ..http import Headers, HttpRequest, HttpResponse

if TYPE_CHECKING:
    from . import Prepare

DEFAULT_TIMEOUT = 30.0
USER_AGENT = "updates2mqtt-oci"


def request_kwargs(request: HttpRequest) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "headers": dict(request.headers),
        # also visible to httpx event hooks and transports
        "extensions": {
            "oci_kind": request.kind,
            "oci_immutable": request.immutable,
            "oci_registry": request.registry,
        },
    }
    if request.body is not None:
        kwargs["content"] = request.body
    return kwargs


def to_response(response: httpx.Response, request: HttpRequest) -> HttpResponse:
    return HttpResponse(
        status_code=response.status_code,
        headers=Headers(response.headers.multi_items()),
        content=response.content,
        request=request,
        url=str(response.url),
        native=response,
    )


class HttpxTransport:
    def __init__(
        self, client: httpx.Client | None = None, prepare: Prepare | None = None, timeout: float = DEFAULT_TIMEOUT
    ) -> None:
        self.owns_client: bool = client is None
        self.client: httpx.Client = client or httpx.Client(timeout=timeout, headers={"User-Agent": USER_AGENT})
        self.prepare: Prepare | None = prepare

    def send(self, request: HttpRequest) -> HttpResponse:
        kwargs: dict[str, Any] = request_kwargs(request)
        if self.prepare:
            self.prepare(request, kwargs)
        native: httpx.Request = self.client.build_request(request.method, request.url, **kwargs)
        try:
            return to_response(self.client.send(native, follow_redirects=True), request)
        except httpx.HTTPError as e:
            raise TransportError(f"{request.method} {request.url} failed: {e}") from e

    def close(self) -> None:
        if self.owns_client:
            self.client.close()


class AsyncHttpxTransport:
    def __init__(
        self, client: httpx.AsyncClient | None = None, prepare: Prepare | None = None, timeout: float = DEFAULT_TIMEOUT
    ) -> None:
        self.owns_client: bool = client is None
        self.client: httpx.AsyncClient = client or httpx.AsyncClient(timeout=timeout, headers={"User-Agent": USER_AGENT})
        self.prepare: Prepare | None = prepare

    async def send(self, request: HttpRequest) -> HttpResponse:
        kwargs: dict[str, Any] = request_kwargs(request)
        if self.prepare:
            self.prepare(request, kwargs)
        native: httpx.Request = self.client.build_request(request.method, request.url, **kwargs)
        try:
            return to_response(await self.client.send(native, follow_redirects=True), request)
        except httpx.HTTPError as e:
            raise TransportError(f"{request.method} {request.url} failed: {e}") from e

    async def aclose(self) -> None:
        if self.owns_client:
            await self.client.aclose()
