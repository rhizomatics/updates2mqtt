"""The same registry conversation over real HTTP, through each transport, sync and async"""

from collections.abc import Callable, Generator
from typing import Any

import httpx
import niquests
import pytest

from tests.oci.fake_registry import FakeRegistry
from tests.oci.test_client import multi_platform
from updates2mqtt.oci import (
    AsyncRegistryClient,
    Credentials,
    HttpRequest,
    RegistryClient,
    StaticCredentials,
    TransportError,
)
from updates2mqtt.oci.http import AsyncTransport, Transport
from updates2mqtt.oci.transports import Prepare, default_async_transport, default_transport
from updates2mqtt.oci.transports.httpx_transport import AsyncHttpxTransport, HttpxTransport
from updates2mqtt.oci.transports.niquests_transport import AsyncNiquestsTransport, NiquestsTransport

REPO = "org/app"

SYNC_TRANSPORTS: dict[str, Callable[[Prepare | None], Transport]] = {
    "httpx": lambda prepare: HttpxTransport(prepare=prepare),
    "niquests": lambda prepare: NiquestsTransport(prepare=prepare),
}
ASYNC_TRANSPORTS: dict[str, Callable[[Prepare | None], AsyncTransport]] = {
    "httpx": lambda prepare: AsyncHttpxTransport(prepare=prepare),
    "niquests": lambda prepare: AsyncNiquestsTransport(prepare=prepare),
}


@pytest.fixture
def served() -> Generator[tuple[FakeRegistry, str]]:
    fake = FakeRegistry(users={"me": "secret"}, redirect_blobs=True, page_size=1)
    multi_platform(fake)
    fake.tags[REPO] += ["1.0", "2.0"]
    with fake.serve() as registry:
        yield fake, registry


def credentials(registry: str) -> StaticCredentials:
    return StaticCredentials({registry: Credentials("me", "secret")})


def recorder(kinds: list[str]) -> Prepare:
    def prepare(request: HttpRequest, kwargs: dict[str, Any]) -> None:
        kinds.append(request.kind)
        kwargs["headers"]["X-Prepared"] = request.kind

    return prepare


@pytest.mark.parametrize("name", SYNC_TRANSPORTS)
def test_sync_transport(name: str, served: tuple[FakeRegistry, str]) -> None:
    fake, registry = served
    kinds: list[str] = []
    with RegistryClient(SYNC_TRANSPORTS[name](recorder(kinds)), credentials=credentials(registry)) as uut:
        image = uut.resolve(f"{registry}/{REPO}:latest", "linux/arm/v7")
        assert image.labels == {"platform": "linux/arm/v7"}
        assert image.manifest is not None
        assert uut.head_manifest(f"{registry}/{REPO}:latest") == image.digest
        assert uut.list_tags(f"{registry}/{REPO}") == ["1.0", "2.0", "latest"]
    assert kinds[:5] == ["manifest", "token", "manifest", "manifest", "blob"]
    # token fetched with credentials, blob redirect followed
    assert fake.token_requests[0].headers["authorization"].startswith("Basic ")
    assert any(r.path.startswith("/cdn/") for r in fake.requests)
    assert all(r.headers.get("x-prepared") for r in fake.requests)


@pytest.mark.parametrize("name", ASYNC_TRANSPORTS)
async def test_async_transport(name: str, served: tuple[FakeRegistry, str]) -> None:
    fake, registry = served
    kinds: list[str] = []
    async with AsyncRegistryClient(ASYNC_TRANSPORTS[name](recorder(kinds)), credentials=credentials(registry)) as uut:
        image = await uut.resolve(f"{registry}/{REPO}:latest", "linux/amd64")
        assert image.labels == {"platform": "linux/amd64"}
        assert await uut.list_tags(f"{registry}/{REPO}", limit=2) == ["1.0", "2.0"]
        assert await uut.list_referrers(f"{registry}/{REPO}", image.digest) == []
    assert "token" in kinds
    assert any(r.path.startswith("/cdn/") for r in fake.requests)


def test_injected_clients_used(served: tuple[FakeRegistry, str]) -> None:
    _fake, registry = served
    hooked: list[str] = []
    http = httpx.Client(event_hooks={"request": [lambda r: hooked.append(r.extensions["oci_kind"])]})
    session = niquests.Session()
    for transport in (HttpxTransport(http), NiquestsTransport(session)):
        with RegistryClient(transport, credentials=credentials(registry)) as uut:
            assert uut.get_manifest(f"{registry}/{REPO}:latest").is_index
    # httpx extensions reach event hooks, e.g. for a caching layer
    assert hooked[:3] == ["manifest", "token", "manifest"]
    # not closed, as owned by the caller
    assert not http.is_closed
    http.close()
    session.close()


def test_default_transports_prefer_niquests() -> None:
    assert isinstance(default_transport(), NiquestsTransport)
    assert isinstance(default_async_transport(), AsyncNiquestsTransport)


@pytest.mark.parametrize("name", SYNC_TRANSPORTS)
def test_sync_unreachable(name: str) -> None:
    with RegistryClient(SYNC_TRANSPORTS[name](None)) as uut, pytest.raises(TransportError):
        uut.list_tags("127.0.0.1:9/app")


@pytest.mark.parametrize("name", ASYNC_TRANSPORTS)
async def test_async_unreachable(name: str) -> None:
    async with AsyncRegistryClient(ASYNC_TRANSPORTS[name](None)) as uut:
        with pytest.raises(TransportError):
            await uut.list_tags("127.0.0.1:9/app")
