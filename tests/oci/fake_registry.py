"""In-memory distribution API with token auth

Served in process as an OCI `Transport`, as an httpx `MockTransport`, or over real HTTP on
localhost, to test the niquests and httpx transports end to end.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import threading
from collections.abc import Generator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx

from updates2mqtt.oci import Headers, HttpRequest, HttpResponse
from updates2mqtt.oci import media_types as mt

REGISTRY = "registry.example"
SERVICE = "registry.example"

Reply = tuple[int, list[tuple[str, str]], bytes]


def digest_of(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def to_bytes(document: dict[str, Any]) -> bytes:
    return json.dumps(document, sort_keys=True).encode()


def json_reply(status: int, body: Any, headers: list[tuple[str, str]] | None = None) -> Reply:
    return status, [("Content-Type", "application/json"), *(headers or [])], json.dumps(body).encode()


def basic(user: str, password: str) -> str:
    return "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()


@dataclass
class Recorded:
    method: str
    url: str
    headers: dict[str, str]
    body: bytes = b""

    @property
    def host(self) -> str:
        return urlsplit(self.url).netloc

    @property
    def path(self) -> str:
        return urlsplit(self.url).path

    @property
    def params(self) -> dict[str, str]:
        return {k: v[0] for k, v in parse_qs(urlsplit(self.url).query).items()}


@dataclass
class FakeRegistry:
    auth: str | None = "bearer"  # bearer, basic or None for anonymous access
    users: dict[str, str] = field(default_factory=dict)  # required credentials, empty for anonymous tokens
    identity_tokens: set[str] = field(default_factory=set)
    referrers_api: bool = True
    content_digest_header: bool = True
    redirect_blobs: bool = False
    expires_in: int | None = 300
    page_size: int = 2
    rate_limited: bool = False
    realm: str = "https://auth.example/token"
    manifests: dict[tuple[str, str], tuple[str, bytes]] = field(default_factory=dict)
    blobs: dict[str, bytes] = field(default_factory=dict)
    tags: dict[str, list[str]] = field(default_factory=dict)
    referrers: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    requests: list[Recorded] = field(default_factory=list)
    issued: dict[str, str] = field(default_factory=dict)  # token -> scope

    @property
    def token_requests(self) -> list[Recorded]:
        return [r for r in self.requests if r.path == "/token"]

    @property
    def registry_requests(self) -> list[Recorded]:
        return [r for r in self.requests if r.path != "/token"]

    # --- content ---

    def add_manifest(self, repo: str, document: dict[str, Any], tag: str | None = None) -> str:
        raw: bytes = to_bytes(document)
        digest: str = digest_of(raw)
        media_type: str = document.get("mediaType", mt.OCI_MANIFEST)
        self.manifests[repo, digest] = (media_type, raw)
        if tag:
            self.manifests[repo, tag] = (media_type, raw)
            self.tags.setdefault(repo, []).append(tag)
        return digest

    def add_blob(self, document: dict[str, Any]) -> str:
        raw: bytes = to_bytes(document)
        self.blobs[digest_of(raw)] = raw
        return digest_of(raw)

    def add_image(
        self, repo: str, tag: str | None, os: str = "linux", arch: str = "amd64", labels: dict[str, str] | None = None
    ) -> tuple[str, str]:
        """Single platform image manifest, returns manifest and config digests"""
        config_digest: str = self.add_blob(
            {"os": os, "architecture": arch, "created": "2026-01-02T03:04:05Z", "config": {"Labels": labels or {}}}
        )
        manifest_digest: str = self.add_manifest(
            repo,
            {
                "schemaVersion": 2,
                "mediaType": mt.OCI_MANIFEST,
                "config": {"mediaType": mt.OCI_CONFIG, "digest": config_digest, "size": 10},
                "layers": [],
                "annotations": {"source": "manifest"},
            },
            tag,
        )
        return manifest_digest, config_digest

    # --- serving ---

    def handle(self, method: str, url: str, headers: Mapping[str, str], body: bytes = b"") -> Reply:
        lowered: dict[str, str] = {k.lower(): v for k, v in headers.items()}
        recorded = Recorded(method, url, lowered, body)
        self.requests.append(recorded)
        if recorded.path == "/token":
            return self.token(recorded)
        if self.rate_limited:
            return json_reply(429, {"errors": [{"code": "TOOMANYREQUESTS"}]}, [("Retry-After", "42")])
        cdn = re.match(r"^/cdn/(.+)$", recorded.path)
        if cdn:
            raw: bytes | None = self.blobs.get(cdn.group(1))
            return (200, [], raw) if raw is not None else (404, [], b"")
        match = re.match(r"^/v2/(.+)/(manifests|blobs|tags/list|referrers)(?:/(.+))?$", recorded.path)
        if not match:
            return 404, [], b""
        repo, kind, identifier = match.groups()
        challenge: Reply | None = self.check_auth(recorded, repo)
        if challenge is not None:
            return challenge
        if kind == "manifests":
            return self.manifest(recorded, repo, identifier)
        if kind == "blobs":
            if self.redirect_blobs:
                return 307, [("Location", f"/cdn/{identifier}")], b""
            raw = self.blobs.get(identifier)
            return (200, [], raw) if raw is not None else (404, [], b"")
        if kind == "tags/list":
            return self.tag_page(recorded, repo)
        return self.referrer_index(recorded, identifier)

    def check_auth(self, request: Recorded, repo: str) -> Reply | None:
        if self.auth is None:
            return None
        header: str = request.headers.get("authorization", "")
        scope: str = f"repository:{repo}:pull"
        if self.auth == "basic":
            if header in {basic(u, p) for u, p in self.users.items()}:
                return None
            return json_reply(401, {}, [("WWW-Authenticate", f'Basic realm="{REGISTRY}"')])
        if header.startswith("Bearer ") and self.issued.get(header[7:]) == scope:
            return None
        error: str = ',error="insufficient_scope"' if header.startswith("Bearer ") else ""
        # scope first, to check parameter order doesn't matter
        return json_reply(
            401,
            {"errors": [{"code": "UNAUTHORIZED", "message": "authentication required"}]},
            [("WWW-Authenticate", f'Bearer scope="{scope}",realm="{self.realm}",service="{SERVICE}"{error}')],
        )

    def token(self, request: Recorded) -> Reply:
        if request.method == "POST":
            form: dict[str, list[str]] = parse_qs(request.body.decode())
            if form.get("grant_type") != ["refresh_token"] or form.get("refresh_token", [""])[0] not in self.identity_tokens:
                return 401, [], b""
            token: str = f"oauth-{len(self.issued)}"
            self.issued[token] = form.get("scope", [""])[0]
            return json_reply(200, {"access_token": token, "expires_in": self.expires_in})
        if self.users and request.headers.get("authorization") not in {basic(u, p) for u, p in self.users.items()}:
            return 401, [], b""
        token = f"token-{len(self.issued)}"
        self.issued[token] = request.params.get("scope", "")
        body: dict[str, Any] = {"token": token}
        if self.expires_in is not None:
            body["expires_in"] = self.expires_in
        return json_reply(200, body)

    def manifest(self, request: Recorded, repo: str, identifier: str) -> Reply:
        found: tuple[str, bytes] | None = self.manifests.get((repo, identifier))
        if found is None:
            return json_reply(404, {"errors": [{"code": "MANIFEST_UNKNOWN", "message": "not found"}]})
        media_type, raw = found
        accepted: str = request.headers.get("accept", "")
        if accepted and "*/*" not in accepted and media_type not in accepted:
            return json_reply(404, {"errors": [{"code": "MANIFEST_UNKNOWN", "message": "not acceptable"}]})
        headers: list[tuple[str, str]] = [("Content-Type", media_type)]
        if self.content_digest_header:
            headers.append(("Docker-Content-Digest", digest_of(raw)))
        return 200, headers, b"" if request.method == "HEAD" else raw

    def tag_page(self, request: Recorded, repo: str) -> Reply:
        tags: list[str] = sorted(self.tags.get(repo, []))
        size: int = int(request.params.get("n", self.page_size))
        last: str | None = request.params.get("last")
        remaining: list[str] = [t for t in tags if last is None or t > last]
        page: list[str] = remaining[:size]
        headers: list[tuple[str, str]] = []
        if len(remaining) > size:
            headers.append(("Link", f'</v2/{repo}/tags/list?n={size}&last={page[-1]}>; rel="next"'))
        return json_reply(200, {"name": repo, "tags": page}, headers)

    def referrer_index(self, request: Recorded, digest: str) -> Reply:
        if not self.referrers_api:
            return 404, [], b""
        descriptors: list[dict[str, Any]] = self.referrers.get(digest, [])
        artifact_type: str | None = request.params.get("artifactType")
        headers: list[tuple[str, str]] = []
        if artifact_type:
            descriptors = [d for d in descriptors if d.get("artifactType") == artifact_type]
            headers.append(("OCI-Filters-Applied", "artifactType"))
        status, base_headers, body = json_reply(
            200, {"schemaVersion": 2, "mediaType": mt.OCI_INDEX, "manifests": descriptors}, headers
        )
        return status, [("Content-Type", mt.OCI_INDEX), *[h for h in base_headers if h[0] != "Content-Type"]], body

    # --- ways to reach it ---

    def transport(self) -> InProcessTransport:
        return InProcessTransport(self)

    def httpx_transport(self) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            status, headers, body = self.handle(request.method, str(request.url), request.headers, request.content)
            return httpx.Response(status, headers=headers, content=body)

        return httpx.MockTransport(handler)

    @contextmanager
    def serve(self) -> Generator[str]:
        """Real HTTP server on localhost, yielding its registry name, e.g. 127.0.0.1:43123"""
        fake: FakeRegistry = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def respond(self) -> None:
                length: int = int(self.headers.get("Content-Length") or 0)
                body: bytes = self.rfile.read(length) if length else b""
                host: str = self.headers.get("Host", "")
                status, headers, content = fake.handle(self.command, f"http://{host}{self.path}", dict(self.headers), body)
                self.send_response(status)
                for name, value in headers:
                    self.send_header(name, value)
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(content)

            do_GET = do_POST = do_HEAD = respond

            def log_message(self, *_args: Any) -> None:
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        registry: str = f"127.0.0.1:{server.server_address[1]}"
        self.realm = f"http://{registry}/token"
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield registry
        finally:
            server.shutdown()
            server.server_close()


class InProcessTransport:
    """Calls the fake directly, following redirects as the real transports do"""

    def __init__(self, fake: FakeRegistry) -> None:
        self.fake: FakeRegistry = fake
        self.closed: bool = False

    def send(self, request: HttpRequest) -> HttpResponse:
        url: str = request.url
        for _ in range(5):
            status, headers, body = self.fake.handle(request.method, url, request.headers, request.body or b"")
            location: str | None = next((v for k, v in headers if k.lower() == "location"), None)
            if status in (301, 302, 303, 307, 308) and location:
                parts = urlsplit(url)
                url = f"{parts.scheme}://{parts.netloc}{location}"
                continue
            return HttpResponse(status, Headers(headers), body, request, url=url)
        raise RuntimeError("Too many redirects")

    def close(self) -> None:
        self.closed = True
