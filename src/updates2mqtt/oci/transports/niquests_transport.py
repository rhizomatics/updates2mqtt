"""niquests transport, takes a session so it can be one with caching"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import niquests

from ..errors import TransportError
from ..http import Headers, HttpRequest, HttpResponse

if TYPE_CHECKING:
    from . import Prepare

DEFAULT_TIMEOUT = 30.0
USER_AGENT = "updates2mqtt-oci"


def request_kwargs(request: HttpRequest, timeout: float) -> dict[str, Any]:
    return {
        "headers": dict(request.headers),
        "data": request.body,
        "timeout": timeout,
        "allow_redirects": True,
    }


def to_response(response: niquests.Response, request: HttpRequest) -> HttpResponse:
    return HttpResponse(
        status_code=response.status_code or 0,
        # repeated headers arrive joined with commas, which the challenge and link parsing allow for
        headers=Headers(response.headers.items()),
        content=response.content or b"",
        request=request,
        url=str(response.url or request.url),
        native=response,
    )


def new_session(session_class: type[Any]) -> Any:
    session: Any = session_class()
    session.headers["User-Agent"] = USER_AGENT
    return session


class NiquestsTransport:
    def __init__(
        self, session: niquests.Session | None = None, prepare: Prepare | None = None, timeout: float = DEFAULT_TIMEOUT
    ) -> None:
        self.owns_session: bool = session is None
        self.session: niquests.Session = session or new_session(niquests.Session)
        self.prepare: Prepare | None = prepare
        self.timeout: float = timeout

    def send(self, request: HttpRequest) -> HttpResponse:
        kwargs: dict[str, Any] = request_kwargs(request, self.timeout)
        if self.prepare:
            self.prepare(request, kwargs)
        try:
            return to_response(self.session.request(request.method, request.url, **kwargs), request)
        except niquests.RequestException as e:
            raise TransportError(f"{request.method} {request.url} failed: {e}") from e

    def close(self) -> None:
        if self.owns_session:
            self.session.close()


class AsyncNiquestsTransport:
    def __init__(
        self,
        session: niquests.AsyncSession | None = None,
        prepare: Prepare | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.owns_session: bool = session is None
        self.session: niquests.AsyncSession = session or new_session(niquests.AsyncSession)
        self.prepare: Prepare | None = prepare
        self.timeout: float = timeout

    async def send(self, request: HttpRequest) -> HttpResponse:
        kwargs: dict[str, Any] = request_kwargs(request, self.timeout)
        if self.prepare:
            self.prepare(request, kwargs)
        try:
            response: niquests.Response = await self.session.request(request.method, request.url, **kwargs)
        except niquests.RequestException as e:
            raise TransportError(f"{request.method} {request.url} failed: {e}") from e
        return to_response(response, request)

    async def aclose(self) -> None:
        if self.owns_session:
            await self.session.close()
