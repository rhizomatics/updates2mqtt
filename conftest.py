# python
import asyncio
import re
import uuid
from collections.abc import AsyncGenerator, Callable
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import httpx
import paho.mqtt.client
import pytest
from docker import DockerClient
from docker.models.containers import Container, ContainerCollection
from docker.models.images import Image, RegistryData
from omegaconf import DictConfig, OmegaConf
from pytest_httpx import HTTPXMock

import updates2mqtt.app
from updates2mqtt.app import (
    App,  # relative import as required
    MqttPublisher,
)
from updates2mqtt.config import Config, NodeConfig
from updates2mqtt.model import Discovery, ReleaseProvider


def pytest_addoption(parser) -> None:  # noqa: ANN001
    parser.addoption("--runslow", action="store_true", default=False, help="run slow tests")


def pytest_configure(config) -> None:  # noqa: ANN001
    config.addinivalue_line("markers", "slow: mark test as slow to run")


def pytest_collection_modifyitems(config, items) -> None:  # noqa: ANN001
    if config.getoption("--runslow"):
        # --runslow given in cli: do not skip slow tests
        return
    skip_slow = pytest.mark.skip(reason="need --runslow option to run")
    for item in items:
        if "slow" in item.keywords:
            item.add_marker(skip_slow)


@pytest.fixture
def app_with_mocked_external_dependencies(
    monkeypatch,  # noqa: ANN001
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
    return [Discovery(mock_provider, "thing-1", "test001", "testbed01", can_update=True, update_type="TestRun")]


@pytest.fixture
def mock_discovery_generator(mock_discoveries: list[Discovery]) -> Callable[..., AsyncGenerator[Discovery, Any]]:
    async def g(*args: Any) -> AsyncGenerator[Discovery]:  # noqa: ARG001
        for d in mock_discoveries:
            await asyncio.sleep(0.001)
            yield d

    return g


@pytest.fixture
def mock_provider_class(mock_provider: ReleaseProvider) -> type:
    class MockReleaseProvider(ReleaseProvider):
        def __new__(cls, *args: Any, **kwargs: Any) -> "MockReleaseProvider":  # noqa: ARG004
            return cast("MockReleaseProvider", mock_provider)

    return MockReleaseProvider


@pytest.fixture
def mock_publisher_class(mock_publisher: MqttPublisher) -> type:
    class MockPublisher(MqttPublisher):
        def __new__(cls, *args: Any, **kwargs: Any) -> "MockPublisher":  # noqa: ARG004
            return cast("MockPublisher", mock_publisher)

    return MockPublisher


@pytest.fixture
def mock_provider() -> ReleaseProvider:
    provider: ReleaseProvider = AsyncMock(spec=ReleaseProvider)
    provider.source_type = "unit_test"
    provider.command.return_value = True  # type: ignore[attr-defined]
    provider.resolve.return_value = Discovery(  # type: ignore[attr-defined]
        provider, "fooey", session="test-mqtt-123", node="node002", current_version="v2", latest_version="v2"
    )
    return provider


@pytest.fixture
def mock_publisher(mock_mqtt_client: paho.mqtt.client.Client) -> MqttPublisher:
    publisher: MqttPublisher = AsyncMock(MqttPublisher)
    publisher.client = mock_mqtt_client
    return publisher


@pytest.fixture
def mock_mqtt_client() -> paho.mqtt.client.Client:
    return MagicMock(spec=paho.mqtt.client.Client, name="MQTT Client Fixture")


def digest_for_ref(v: str, short: bool = True) -> str:
    d: str
    match v:
        case "testy/mctest:latest":
            d = "sha256:c53853875750"
        case "testy/mctest":
            d = "sha256:9e2bbca079382"
        case "ubuntu":
            d = "sha256:85a5385853bd3"
        case _:
            d = "sha256:9999999999999"
    return d if short else f"{d}{'0' * 52}"


@pytest.fixture
def mock_registry(httpx_mock: HTTPXMock) -> HTTPXMock:
    # TODO: finish
    def custom_response(request: httpx.Request) -> httpx.Response:
        if "/token" in request.url.path:
            return httpx.Response(
                status_code=200,
                json={"token": "fooey"},  # nosec
            )
        m = re.match(r"/v2/([A-Za-z0-9/]+/manifests/(sha256:[0-9]+))", request.url.path)
        if m:
            if m.group(2) == f"{digest_for_ref(m.group(1), short=False)}111":
                return httpx.Response(
                    status_code=200,
                    json={"config": {"digest": digest_for_ref(m.group(1), short=False)}, "annotations": {"test.type": "unit"}},
                )
            return httpx.Response(status_code=404)
        m = re.match(r"/v2/([A-Za-z0-9/]+/manifests/([A-Za-z0-9:]+))", request.url.path)
        if m:
            return httpx.Response(
                status_code=200,
                json={
                    "manifests": [
                        {
                            "platform": {"os": "linux", "architecture": "arm64"},
                            "mediaType": "test_manifest",
                            "digest": f"{digest_for_ref(m.group(1), short=False)}111",
                        },
                        {
                            "platform": {"os": "macos", "architecture": "arm64"},
                            "mediaType": "test_manifest",
                            "digest": f"{digest_for_ref(m.group(1), short=False)}111",
                        },
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
        reg_data = Mock(spec=RegistryData, image_name=v, id=uuid.uuid4(), attrs={})
        reg_data.short_id = digest_for_ref(v)
        return reg_data

    client.images.get_registry_data = Mock(side_effect=reg_data_select)

    client.containers = coll
    coll.list.return_value = [
        build_mock_container("testy/mctest:latest", opsys="macos"),
        build_mock_container("ubuntu"),
        build_mock_container("common/pkg"),
        build_mock_container(
            "testy/mctest",
            picture="https://piccy",
            relnotes="https://release",
            arch="amd64",
        ),
    ]
    patch("docker.from_env", return_value=client)
    return client


def build_mock_container(
    tag: str, picture: str | None = None, relnotes: str | None = None, opsys: str = "linux", arch: str = "arm64"
) -> Container:
    c = Mock(spec=Container)
    c.image = Mock(spec=Image)
    c.image.tags = [tag]
    c.image.labels = {}
    c.image.attrs = {}
    c.image.attrs["Os"] = opsys
    c.image.attrs["Architecture"] = arch
    bare_tag = tag.split(":")[0]
    long_hash = "9e2bbca079387d7965c3a9cee6d0c53f4f4e63ff7637877a83c4c05f2a666112"
    c.image.attrs["RepoDigests"] = [f"{bare_tag}@sha256:{long_hash}"]
    c.labels = {}
    c.attrs = {}
    c.attrs["Config"] = {}
    c.attrs["Config"]["Env"] = []
    c.attrs["Config"]["Labels"] = c.labels
    if picture:
        c.attrs["Config"]["Env"].append(f"UPD2MQTT_PICTURE={picture}")
    if relnotes:
        c.attrs["Config"]["Env"].append(f"UPD2MQTT_RELNOTES={relnotes}")
    return c


@pytest.fixture
def node_cfg() -> NodeConfig:
    node_config = OmegaConf.structured(NodeConfig)
    node_config.name = "TESTBED"
    return node_config
