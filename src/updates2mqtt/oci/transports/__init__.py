"""Transports for the registry client, each importing its HTTP library only when used

Each takes an optional `prepare(request, kwargs)` hook, called with the keyword arguments about to
be passed to the HTTP library, so a caching layer can act on `request.kind` and `request.immutable`,
e.g. setting hishel extensions for httpx, or expiry options for a caching niquests session.
"""

from __future__ import annotations

import importlib.util
from collections.abc import Callable
from typing import Any

from ..http import AsyncTransport, HttpRequest, Transport

Prepare = Callable[[HttpRequest, dict[str, Any]], None]


def default_transport() -> Transport:
    if importlib.util.find_spec("niquests"):
        from .niquests_transport import NiquestsTransport

        return NiquestsTransport()
    if importlib.util.find_spec("httpx"):
        from .httpx_transport import HttpxTransport

        return HttpxTransport()
    raise ImportError("No HTTP library for the registry client, install niquests or httpx")


def default_async_transport() -> AsyncTransport:
    if importlib.util.find_spec("niquests"):
        from .niquests_transport import AsyncNiquestsTransport

        return AsyncNiquestsTransport()
    if importlib.util.find_spec("httpx"):
        from .httpx_transport import AsyncHttpxTransport

        return AsyncHttpxTransport()
    raise ImportError("No HTTP library for the registry client, install niquests or httpx")


__all__ = ["Prepare", "default_async_transport", "default_transport"]
