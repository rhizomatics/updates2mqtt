"""Transport-neutral HTTP types, so the protocol logic works over httpx, niquests or anything else

A transport sends an `HttpRequest`, following redirects and dropping Authorization on a change
of host, as httpx and niquests both do, and returns an `HttpResponse` with the body read.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field, replace
from typing import Any, Protocol
from urllib.parse import urlencode, urljoin, urlsplit, urlunsplit

_LINK_RE = re.compile(r"<([^>]*)>\s*((?:;\s*[^;,]+)*)")


class Headers(Mapping[str, str]):
    """Case-insensitive, multi-valued, read-only headers"""

    def __init__(self, items: Mapping[str, str] | Iterable[tuple[str, str]] | None = None) -> None:
        pairs: list[tuple[str, str]] = []
        if isinstance(items, Mapping):
            pairs = [(str(k), str(v)) for k, v in items.items()]
        elif items is not None:
            pairs = [(str(k), str(v)) for k, v in items]
        self.items_list: list[tuple[str, str]] = [(k.lower(), v) for k, v in pairs]

    def __getitem__(self, key: str) -> str:
        values: list[str] = self.get_list(key)
        if not values:
            raise KeyError(key)
        return ", ".join(values)

    def get_list(self, key: str) -> list[str]:
        key = key.lower()
        return [v for k, v in self.items_list if k == key]

    def __iter__(self) -> Iterator[str]:
        return iter(dict.fromkeys(k for k, _ in self.items_list))

    def __len__(self) -> int:
        return len(dict.fromkeys(k for k, _ in self.items_list))

    def __repr__(self) -> str:
        return f"Headers({self.items_list!r})"


@dataclass(frozen=True)
class HttpRequest:
    """What to send, plus what the client knows about it, for auth and for any caching layer

    kind: manifest, blob, tags, referrers or token
    immutable: content addressed by digest, so safe to cache indefinitely
    registry: whose credentials apply, as normalized by `Reference`
    scope: token scope the request needs, e.g. `repository:org/app:pull`
    """

    method: str
    url: str
    headers: Mapping[str, str] = field(default_factory=dict)
    form: Mapping[str, str] | None = None
    kind: str = ""
    immutable: bool = False
    registry: str | None = None
    scope: str | None = None

    def with_header(self, name: str, value: str) -> HttpRequest:
        headers: dict[str, str] = {k: v for k, v in self.headers.items() if k.lower() != name.lower()}
        headers[name] = value
        return replace(self, headers=headers)

    def header(self, name: str) -> str | None:
        return next((v for k, v in self.headers.items() if k.lower() == name.lower()), None)

    @property
    def host(self) -> str:
        return urlsplit(self.url).netloc

    @property
    def body(self) -> bytes | None:
        return urlencode(self.form).encode() if self.form is not None else None


@dataclass
class HttpResponse:
    status_code: int
    headers: Headers
    content: bytes
    request: HttpRequest
    url: str = ""  # final, after redirects
    # the transport's own response, e.g. to read cache metadata it attaches
    native: Any = field(default=None, repr=False)

    @property
    def is_success(self) -> bool:
        return 200 <= self.status_code < 300

    def json(self) -> Any:
        return json.loads(self.content)

    def next_link(self) -> str | None:
        """Absolute URL of the RFC 8288 `rel="next"` Link, as used for pagination"""
        for header in self.headers.get_list("link"):
            for target, params in _LINK_RE.findall(header):
                if re.search(r'rel\s*=\s*"?([^";]*\s)?next(\s[^";]*)?"?', params):
                    return urljoin(self.url or self.request.url, target)
        return None


def with_query(url: str, params: Mapping[str, Any] | None) -> str:
    """Append parameters to a URL that may already have a query"""
    if not params:
        return url
    parts = urlsplit(url)
    query: str = "&".join(q for q in (parts.query, urlencode(params)) if q)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))


class Transport(Protocol):
    def send(self, request: HttpRequest) -> HttpResponse: ...

    def close(self) -> None: ...


class AsyncTransport(Protocol):
    async def send(self, request: HttpRequest) -> HttpResponse: ...

    async def aclose(self) -> None: ...
