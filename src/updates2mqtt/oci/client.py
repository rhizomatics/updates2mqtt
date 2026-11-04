"""Read-only clients for the OCI distribution API

Each operation is a generator yielding `HttpRequest` and receiving `HttpResponse`, composed with
the auth flow, so the protocol logic is written once, free of I/O, and driven by either
`RegistryClient` or `AsyncRegistryClient` over any transport, see `transports`.
"""

from __future__ import annotations

import logging
from collections.abc import Collection, Generator, Sequence
from typing import Any, Self, TypeVar

from .auth import CredentialStore, RegistryAuth, parse_retry_after
from .errors import AuthenticationError, NotFoundError, OCIError, RateLimitedError, RegistryError
from .http import AsyncTransport, HttpRequest, HttpResponse, Transport, with_query
from .media_types import ALL_MANIFEST_MEDIA_TYPES, OCI_INDEX
from .models import Blob, Descriptor, Manifest, Platform, ResolvedImage, verify_digest
from .reference import Reference, is_digest, normalize_registry

log = logging.getLogger(__name__)

T = TypeVar("T")
Flow = Generator[HttpRequest, HttpResponse, T]

HEADER_CONTENT_DIGEST = "docker-content-digest"
HEADER_FILTERS_APPLIED = "oci-filters-applied"
# served over plain http, as Docker allows for local registries
DEFAULT_INSECURE_REGISTRIES: frozenset[str] = frozenset({"localhost", "127.0.0.1", "[::1]"})

RefLike = Reference | str


def as_reference(ref: RefLike) -> Reference:
    return ref if isinstance(ref, Reference) else Reference.parse(ref)


def as_platform(platform: Platform | str | None) -> Platform | None:
    return Platform.parse(platform) if isinstance(platform, str) else platform


def registry_host(registry: str) -> str:
    """Host without port, keeping brackets for IPv6"""
    if registry.startswith("["):
        return registry[: registry.index("]") + 1] if "]" in registry else registry
    return registry.split(":", 1)[0]


def error_details(response: HttpResponse) -> list[dict[str, Any]]:
    try:
        body: Any = response.json()
    except ValueError:
        return []
    errors: Any = body.get("errors") if isinstance(body, dict) else None
    return [e for e in errors if isinstance(e, dict)] if isinstance(errors, list) else []


def check_response(response: HttpResponse, what: str) -> None:
    if response.is_success:
        return
    errors: list[dict[str, Any]] = error_details(response)
    detail: str = "; ".join(f"{e.get('code')}: {e.get('message')}" for e in errors)
    message: str = f"{what}: {response.status_code} {detail}".rstrip()
    status: int = response.status_code
    if status == 429:
        raise RateLimitedError(message, retry_after=parse_retry_after(response.headers.get("retry-after")), errors=errors)
    if status in (401, 403):
        raise AuthenticationError(message, status, errors)
    if status == 404:
        raise NotFoundError(message, status, errors)
    raise RegistryError(message, status, errors)


class RegistryProtocol:
    """Request building and the operation flows, shared by the sync and async clients"""

    def __init__(
        self,
        credentials: CredentialStore | None = None,
        insecure_registries: Collection[str] = DEFAULT_INSECURE_REGISTRIES,
        auth: RegistryAuth | None = None,
    ) -> None:
        self.auth: RegistryAuth = auth or RegistryAuth(credentials)
        self.insecure_registries: frozenset[str] = frozenset(normalize_registry(r) for r in insecure_registries)

    def url(self, ref: Reference, path: str) -> str:
        insecure: bool = ref.registry in self.insecure_registries or registry_host(ref.registry) in self.insecure_registries
        return f"{'http' if insecure else 'https'}://{ref.api_host}/v2/{ref.repository}/{path}"

    def request(
        self,
        method: str,
        url: str,
        ref: Reference,
        kind: str,
        accept: Sequence[str] | None = None,
        token: str | None = None,
        immutable: bool = False,
        params: dict[str, Any] | None = None,
    ) -> HttpRequest:
        headers: dict[str, str] = {}
        if accept:
            headers["Accept"] = ", ".join(accept)
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return HttpRequest(
            method,
            with_query(url, params),
            headers=headers,
            kind=kind,
            immutable=immutable,
            registry=ref.registry,
            scope=f"repository:{ref.repository}:pull",
        )

    def authenticated(self, flow: Flow[T]) -> Flow[T]:
        """Pass each request of an operation through the auth flow"""
        try:
            request: HttpRequest = next(flow)
            while True:
                response: HttpResponse = yield from self.auth.flow(request)
                request = flow.send(response)
        except StopIteration as done:
            result: T = done.value
            return result

    def manifest_flow(self, ref: Reference, accept: Sequence[str], token: str | None) -> Flow[Manifest]:
        identifier: str = ref.identifier
        digest: str | None = identifier if is_digest(identifier) else None
        response: HttpResponse = yield self.request(
            "GET", self.url(ref, f"manifests/{identifier}"), ref, "manifest", accept, token, immutable=digest is not None
        )
        check_response(response, f"Manifest {ref}")
        return Manifest.from_response(response, expected_digest=digest)

    def head_manifest_flow(self, ref: Reference, accept: Sequence[str], token: str | None) -> Flow[str | None]:
        response: HttpResponse = yield self.request(
            "HEAD", self.url(ref, f"manifests/{ref.identifier}"), ref, "manifest", accept, token
        )
        check_response(response, f"Manifest {ref}")
        return response.headers.get(HEADER_CONTENT_DIGEST)

    def blob_flow(self, ref: Reference, digest: str, media_type: str | None, token: str | None) -> Flow[Blob]:
        response: HttpResponse = yield self.request(
            "GET", self.url(ref, f"blobs/{digest}"), ref, "blob", [media_type] if media_type else None, token, immutable=True
        )
        check_response(response, f"Blob {digest} of {ref}")
        verify_digest(response.content, digest)
        return Blob(digest=digest, content=response.content, media_type=media_type, response=response)

    def tags_flow(self, ref: Reference, page_size: int | None, limit: int | None, token: str | None) -> Flow[list[str]]:
        tags: list[str] = []
        url: str | None = self.url(ref, "tags/list")
        params: dict[str, Any] | None = {"n": page_size} if page_size else None
        while url is not None:
            response: HttpResponse = yield self.request("GET", url, ref, "tags", token=token, params=params)
            check_response(response, f"Tags of {ref}")
            body: Any = response.json()
            tags.extend((body.get("tags") or []) if isinstance(body, dict) else [])
            if limit is not None and len(tags) >= limit:
                return tags[:limit]
            # next page per the Link header, which already carries the page size
            url = response.next_link()
            params = None
        return tags

    def referrers_flow(
        self, ref: Reference, digest: str, artifact_type: str | None, token: str | None
    ) -> Flow[list[Descriptor]]:
        params: dict[str, Any] | None = {"artifactType": artifact_type} if artifact_type else None
        response: HttpResponse = yield self.request(
            "GET", self.url(ref, f"referrers/{digest}"), ref, "referrers", [OCI_INDEX], token, params=params
        )
        filtered: bool = False
        if response.status_code == 404:
            # registries without the referrers API use a tag named after the subject digest
            fallback: Reference = Reference(ref.registry, ref.repository, tag=digest.replace(":", "-"))
            log.debug("No referrers API at %s, trying tag schema %s", ref.registry, fallback)
            try:
                index: Manifest = yield from self.manifest_flow(fallback, [OCI_INDEX], token)
            except NotFoundError:
                return []
        else:
            check_response(response, f"Referrers of {digest} in {ref}")
            index = Manifest.from_response(response)
            filtered = "artifactType" in response.headers.get(HEADER_FILTERS_APPLIED, "")
        descriptors: list[Descriptor] = index.manifests
        if artifact_type and not filtered:
            descriptors = [d for d in descriptors if d.artifact_type == artifact_type]
        return descriptors

    def resolve_flow(
        self, ref: Reference, platform: Platform | None, fetch_config: bool, token: str | None
    ) -> Flow[ResolvedImage]:
        top: Manifest = yield from self.manifest_flow(ref, ALL_MANIFEST_MEDIA_TYPES, token)
        index: Manifest | None = None
        manifest: Manifest | None = top
        if top.is_index:
            index, manifest = top, None
            entry: Descriptor | None = top.select(platform) if platform else None
            if entry is not None:
                accept: Sequence[str] = [entry.media_type] if entry.media_type else ALL_MANIFEST_MEDIA_TYPES
                manifest = yield from self.manifest_flow(ref.with_digest(entry.digest), accept, token)
            elif platform:
                log.debug("No %s entry in index for %s", platform, ref)
        resolved = ResolvedImage(reference=ref, digest=top.digest, index=index, manifest=manifest)
        config: Descriptor | None = manifest.config if manifest else None
        if fetch_config and config is not None:
            resolved.config_blob = yield from self.blob_flow(ref, config.digest, config.media_type, token)
            try:
                resolved.config = resolved.config_blob.json()
            except ValueError as e:
                raise OCIError(f"Config {config.digest} of {ref} isn't JSON") from e
        return resolved


class RegistryClient(RegistryProtocol):
    """Blocking client, over any `Transport`, by default whichever of niquests or httpx is installed"""

    def __init__(
        self,
        transport: Transport | None = None,
        *,
        credentials: CredentialStore | None = None,
        insecure_registries: Collection[str] = DEFAULT_INSECURE_REGISTRIES,
        auth: RegistryAuth | None = None,
    ) -> None:
        super().__init__(credentials, insecure_registries, auth)
        self.owns_transport: bool = transport is None
        if transport is None:
            from .transports import default_transport

            transport = default_transport()
        self.transport: Transport = transport

    def run(self, flow: Flow[T]) -> T:
        authenticated: Flow[T] = self.authenticated(flow)
        try:
            request: HttpRequest = next(authenticated)
            while True:
                request = authenticated.send(self.transport.send(request))
        except StopIteration as done:
            result: T = done.value
            return result

    def get_manifest(
        self, ref: RefLike, *, accept: Sequence[str] = ALL_MANIFEST_MEDIA_TYPES, token: str | None = None
    ) -> Manifest:
        return self.run(self.manifest_flow(as_reference(ref), accept, token))

    def head_manifest(
        self, ref: RefLike, *, accept: Sequence[str] = ALL_MANIFEST_MEDIA_TYPES, token: str | None = None
    ) -> str | None:
        """Digest of what a reference points to, without fetching it, if the registry says"""
        return self.run(self.head_manifest_flow(as_reference(ref), accept, token))

    def get_blob(self, ref: RefLike, digest: str, *, media_type: str | None = None, token: str | None = None) -> Blob:
        return self.run(self.blob_flow(as_reference(ref), digest, media_type, token))

    def list_tags(
        self, ref: RefLike, *, page_size: int | None = None, limit: int | None = None, token: str | None = None
    ) -> list[str]:
        return self.run(self.tags_flow(as_reference(ref), page_size, limit, token))

    def list_referrers(
        self, ref: RefLike, digest: str, *, artifact_type: str | None = None, token: str | None = None
    ) -> list[Descriptor]:
        return self.run(self.referrers_flow(as_reference(ref), digest, artifact_type, token))

    def resolve(
        self,
        ref: RefLike,
        platform: Platform | str | None = None,
        *,
        fetch_config: bool = True,
        token: str | None = None,
    ) -> ResolvedImage:
        """Manifest, and config, for a platform, without a platform an index isn't descended"""
        return self.run(self.resolve_flow(as_reference(ref), as_platform(platform), fetch_config, token))

    def close(self) -> None:
        if self.owns_transport:
            self.transport.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


class AsyncRegistryClient(RegistryProtocol):
    """Asyncio client, over any `AsyncTransport`, by default whichever of niquests or httpx is installed

    Credential helpers, if configured, are run synchronously on first use for each registry
    """

    def __init__(
        self,
        transport: AsyncTransport | None = None,
        *,
        credentials: CredentialStore | None = None,
        insecure_registries: Collection[str] = DEFAULT_INSECURE_REGISTRIES,
        auth: RegistryAuth | None = None,
    ) -> None:
        super().__init__(credentials, insecure_registries, auth)
        self.owns_transport: bool = transport is None
        if transport is None:
            from .transports import default_async_transport

            transport = default_async_transport()
        self.transport: AsyncTransport = transport

    async def run(self, flow: Flow[T]) -> T:
        authenticated: Flow[T] = self.authenticated(flow)
        try:
            request: HttpRequest = next(authenticated)
            while True:
                request = authenticated.send(await self.transport.send(request))
        except StopIteration as done:
            result: T = done.value
            return result

    async def get_manifest(
        self, ref: RefLike, *, accept: Sequence[str] = ALL_MANIFEST_MEDIA_TYPES, token: str | None = None
    ) -> Manifest:
        return await self.run(self.manifest_flow(as_reference(ref), accept, token))

    async def head_manifest(
        self, ref: RefLike, *, accept: Sequence[str] = ALL_MANIFEST_MEDIA_TYPES, token: str | None = None
    ) -> str | None:
        return await self.run(self.head_manifest_flow(as_reference(ref), accept, token))

    async def get_blob(self, ref: RefLike, digest: str, *, media_type: str | None = None, token: str | None = None) -> Blob:
        return await self.run(self.blob_flow(as_reference(ref), digest, media_type, token))

    async def list_tags(
        self, ref: RefLike, *, page_size: int | None = None, limit: int | None = None, token: str | None = None
    ) -> list[str]:
        return await self.run(self.tags_flow(as_reference(ref), page_size, limit, token))

    async def list_referrers(
        self, ref: RefLike, digest: str, *, artifact_type: str | None = None, token: str | None = None
    ) -> list[Descriptor]:
        return await self.run(self.referrers_flow(as_reference(ref), digest, artifact_type, token))

    async def resolve(
        self,
        ref: RefLike,
        platform: Platform | str | None = None,
        *,
        fetch_config: bool = True,
        token: str | None = None,
    ) -> ResolvedImage:
        return await self.run(self.resolve_flow(as_reference(ref), as_platform(platform), fetch_config, token))

    async def aclose(self) -> None:
        if self.owns_transport:
            await self.transport.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.aclose()
