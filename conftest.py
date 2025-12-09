# python
from collections.abc import AsyncGenerator, Callable
from typing import Any
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import paho.mqtt.client
import pytest
from docker import DockerClient
from docker.models.containers import Container, ContainerCollection
from docker.models.images import Image, RegistryData
from omegaconf import DictConfig, OmegaConf

import updates2mqtt.app
from updates2mqtt.app import (
    App,  # relative import as required
    MqttPublisher,
)
from updates2mqtt.config import Config
from updates2mqtt.model import Discovery, ReleaseProvider


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
            yield d

    return g


@pytest.fixture
def mock_provider_class(mock_provider: ReleaseProvider) -> type:
    class MockReleaseProvider(ReleaseProvider):
        def __new__(cls, *args: Any, **kwargs: Any) -> ReleaseProvider:  # type: ignore[misc] # noqa: ARG004
            return mock_provider

    return MockReleaseProvider


@pytest.fixture
def mock_publisher_class(mock_publisher: MqttPublisher) -> type:
    class MockPublisher(MqttPublisher):
        def __new__(cls, *args: Any, **kwargs: Any) -> MqttPublisher:  # type: ignore[misc] # noqa: ARG004
            return mock_publisher

    return MockPublisher


@pytest.fixture
def mock_provider() -> ReleaseProvider:
    provider: ReleaseProvider = AsyncMock(spec=ReleaseProvider)
    provider.source_type = "unit_test"
    provider.command.return_value = True  # type: ignore[attr-defined]
    provider.resolve.return_value = Discovery(  # type: ignore[attr-defined]
        provider, "fooey", session="test-mqtt-123", node="node002", current_version="v2", latest_version="v2"
    )
    provider.hass_state_format.return_value = {"fixture": "test_exec"}  # type: ignore[attr-defined]
    return provider


@pytest.fixture
def mock_publisher(mock_mqtt_client: paho.mqtt.client.Client) -> MqttPublisher:
    publisher: MqttPublisher = AsyncMock(MqttPublisher)
    publisher.client = mock_mqtt_client
    return publisher


@pytest.fixture
def mock_mqtt_client() -> paho.mqtt.client.Client:
    return MagicMock(spec=paho.mqtt.client.Client, name="MQTT Client Fixture")


@pytest.fixture
def mock_docker_client() -> DockerClient:
    client = Mock(spec=DockerClient)
    coll = Mock(spec=ContainerCollection)

    def reg_data_select(v: str) -> RegistryData:
        reg_data = Mock(spec=RegistryData)
        match v:
            case "testy/mctest:latest":
                reg_data.short_id = "sha256:c5385387575"
            case "testy/mctest":
                reg_data.short_id = "sha256:9e2bbca07938"
            case "ubuntu":
                reg_data.short_id = "sha256:85a5385853bd"
            case _:
                reg_data.short_id = "sha256:999999999999"
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
    c.image.attrs = {}
    c.image.attrs["Os"] = opsys
    c.image.attrs["Architecture"] = arch
    bare_tag = tag.split(":")[0]
    long_hash = "9e2bbca079387d7965c3a9cee6d0c53f4f4e63ff7637877a83c4c05f2a666112"
    c.image.attrs["RepoDigests"] = [f"{bare_tag}@sha256:{long_hash}"]
    c.attrs = {}
    c.attrs["Config"] = {}
    c.attrs["Config"]["Env"] = []
    if picture:
        c.attrs["Config"]["Env"].append(f"UPD2MQTT_PICTURE={picture}")
    if relnotes:
        c.attrs["Config"]["Env"].append(f"UPD2MQTT_RELNOTES={relnotes}")
    return c
