# python
import asyncio
import hashlib
import json
import os
import re
import uuid
from collections.abc import AsyncGenerator, Callable, Generator
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import httpx
import paho.mqtt.client
import pytest
from docker import DockerClient
from docker.models.containers import ContainerCollection
from docker.models.images import RegistryData
from omegaconf import DictConfig, OmegaConf
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.reasoncodes import ReasonCode
from pytest_httpx import HTTPXMock

import updates2mqtt.app
from tests.lib_test import build_mock_container, digest_for_ref, repo_digest_for_ref
from updates2mqtt.app import App
from updates2mqtt.config import Config, NodeConfig
from updates2mqtt.helpers import Throttler
from updates2mqtt.integrations.docker_enrich import ContainerDistributionAPIVersionLookup
from updates2mqtt.model import Discovery, ReleaseProvider
from updates2mqtt.mqtt import MqttPublisher


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--runslow", action="store_true", default=False, help="run slow tests")
    parser.addoption(
        "--integration", action="store_true", default=False, help="run integration tests, needs a local Docker engine"
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "slow: mark test as slow to run")
    config.addinivalue_line("markers", "integration: mark test as needing a local Docker engine, for docker-in-docker")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    skip_slow = pytest.mark.skip(reason="need --runslow option to run")
    skip_integration = pytest.mark.skip(reason="need --integration option to run")
    for item in items:
        if "slow" in item.keywords and not config.getoption("--runslow"):
            item.add_marker(skip_slow)
        if "integration" in item.keywords and not config.getoption("--integration"):
            item.add_marker(skip_integration)


@pytest.fixture(autouse=True)
def isolated_app_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drop the app's own settings from the environment, so a developer's shell doesn't change config defaults"""
    for var in list(os.environ):
        if var.startswith(("MQTT_", "PORTAINER_", "U2M_")) or var == "NODE_NAME":
            monkeypatch.delenv(var)


@pytest.fixture(autouse=True)
def close_registry_lookups(monkeypatch: pytest.MonkeyPatch) -> Generator[None]:
    """Close every registry lookup a test creates, e.g. inside a DockerProvider, so no cache database is left open"""
    created: list[ContainerDistributionAPIVersionLookup] = []
    original_init = ContainerDistributionAPIVersionLookup.__init__

    def tracking_init(self: ContainerDistributionAPIVersionLookup, *args: Any, **kwargs: Any) -> None:
        original_init(self, *args, **kwargs)
        created.append(self)

    monkeypatch.setattr(ContainerDistributionAPIVersionLookup, "__init__", tracking_init)
    yield
    for lookup in created:
        lookup.close()


@pytest.fixture
def mock_throttler() -> Throttler:
    mock = Mock(spec=Throttler)
    mock.check_throttle.return_value = False
    return mock


@pytest.fixture
def app_with_mocked_external_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    mock_provider_class: type,
    mock_publisher_class: type,
) -> App:
    cfg: DictConfig = OmegaConf.structured(Config)
    monkeypatch.setattr(updates2mqtt.app, "load_app_config", lambda *_args, **__kwargs: cfg)
    monkeypatch.setattr(updates2mqtt.app, "DockerProvider", mock_provider_class)
    monkeypatch.setattr(updates2mqtt.app, "MqttPublisher", mock_publisher_class)
    app: App = App()
    return app


@pytest.fixture
def mock_discoveries(mock_provider: ReleaseProvider) -> list[Discovery]:
    return [Discovery(mock_provider, "thing-1", "test001", "testbed01", can_pull=True, update_type="TestRun")]


@pytest.fixture
def mock_discovery_generator(mock_discoveries: list[Discovery]) -> Callable[..., AsyncGenerator[Discovery, Any]]:
    async def g(*args: Any) -> AsyncGenerator[Discovery]:
        for d in mock_discoveries:
            await asyncio.sleep(0.001)
            yield d

    return g


@pytest.fixture
def mock_provider_class(mock_provider: ReleaseProvider) -> type:
    class MockReleaseProvider(ReleaseProvider):
        def __new__(cls, *args: Any, **kwargs: Any) -> "MockReleaseProvider":  # noqa: PYI034
            return cast("MockReleaseProvider", mock_provider)

    return MockReleaseProvider


@pytest.fixture
def mock_publisher_class(mock_publisher: MqttPublisher) -> type:
    class MockPublisher(MqttPublisher):
        def __new__(cls, *args: Any, **kwargs: Any) -> "MockPublisher":  # noqa: PYI034
            return cast("MockPublisher", mock_publisher)

    return MockPublisher


@pytest.fixture
def mock_provider() -> ReleaseProvider:
    provider: ReleaseProvider = AsyncMock(spec=ReleaseProvider)
    provider.source_type = "unit_test"
    provider.command.return_value = True  # type: ignore[attr-defined]
    discovery: Discovery = Discovery(
        provider, "fooey", session="test-mqtt-123", node="node002", current_version="v2", latest_version="v2"
    )
    provider.resolve.return_value = discovery  # type: ignore[attr-defined]
    provider.discoveries = {"fooey": discovery}
    provider.background_tasks = set()
    return provider


@pytest.fixture
def mock_publisher(mock_mqtt_client: paho.mqtt.client.Client) -> MqttPublisher:
    publisher: MqttPublisher = AsyncMock(MqttPublisher)
    publisher.client = mock_mqtt_client
    publisher.command_tasks = set()
    return publisher


@pytest.fixture
def mock_mqtt_client() -> paho.mqtt.client.Client:
    client = MagicMock(spec=paho.mqtt.client.Client, name="MQTT Client Fixture")

    def _loop_start() -> None:
        if client.on_connect:
            client.on_connect(client, None, Mock(), ReasonCode(PacketTypes.CONNACK, "Success"), None)

    client.loop_start.side_effect = _loop_start
    return client


def platform_manifest(name: str) -> bytes:
    return json.dumps(
        {"config": {"digest": repo_digest_for_ref(name, short=False)}, "annotations": {"test.type": "unit"}}
    ).encode()


def platform_manifest_digest(name: str) -> str:
    """Content addressed, as the OCI client verifies"""
    return f"sha256:{hashlib.sha256(platform_manifest(name)).hexdigest()}"


@pytest.fixture
def mock_registry(httpx_mock: HTTPXMock) -> HTTPXMock:
    """Anonymous registry, with arm64 images only, for linux and macos"""

    def custom_response(request: httpx.Request) -> httpx.Response:
        m = re.match(r"/v2/([A-Za-z0-9/]+)/manifests/(sha256:[0-9a-f]+)", request.url.path)
        if m:
            if m.group(2) == platform_manifest_digest(m.group(1)):
                return httpx.Response(status_code=200, content=platform_manifest(m.group(1)))
            return httpx.Response(status_code=404)
        m = re.match(r"/v2/([A-Za-z0-9/]+)/manifests/([A-Za-z0-9:]+)", request.url.path)
        if m:
            return httpx.Response(
                status_code=200,
                json={
                    "manifests": [
                        {
                            "platform": {"os": os_name, "architecture": "arm64"},
                            "mediaType": "test_manifest",
                            "digest": platform_manifest_digest(m.group(1)),
                        }
                        for os_name in ("linux", "macos")
                    ]
                },
            )

        return httpx.Response(status_code=404)

    httpx_mock.add_callback(custom_response, is_reusable=True)
    return httpx_mock


@pytest.fixture
def mock_docker_client() -> DockerClient:
    client = Mock(spec=DockerClient)
    coll = Mock(spec=ContainerCollection)

    def reg_data_select(v: str) -> RegistryData:
        reg_data = Mock(spec=RegistryData, image_name=v, id=uuid.uuid4().hex, attrs={})
        reg_data.id = digest_for_ref(v, short=False)
        reg_data.short_id = digest_for_ref(v, short=True)
        return reg_data

    client.images.get_registry_data = Mock(side_effect=reg_data_select)

    client.containers = coll
    coll.list.return_value = [
        build_mock_container("testy/mctest:latest", opsys="macos"),
        build_mock_container("ubuntu"),
        build_mock_container("common/pkg"),
        build_mock_container(
            "testy/mctest",
            name="piccy",
            picture="https://piccy",
            relnotes="https://release",
            arch="amd64",
            update_available=False,
        ),
    ]
    patch("docker.from_env", return_value=client)
    return client


@pytest.fixture
def node_cfg() -> NodeConfig:
    node_config = OmegaConf.structured(NodeConfig)
    node_config.name = "TESTBED"
    return cast("NodeConfig", node_config)
