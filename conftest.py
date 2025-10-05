from unittest.mock import MagicMock, Mock, patch

import paho.mqtt.client
import pytest
from docker import DockerClient
from docker.models.containers import Container, ContainerCollection
from docker.models.images import Image, RegistryData

from updates2mqtt.model import Discovery, ReleaseProvider


@pytest.fixture
def mock_provider() -> ReleaseProvider:
    provider = Mock(spec=ReleaseProvider)
    provider.source_type = "unit_test"
    provider.command.return_value = True
    provider.resolve.return_value = Discovery(
        provider, "fooey", session="test-mqtt-123", current_version="v2", latest_version="v2"
    )
    provider.hass_state_format.return_value = {"fixture": "test_exec"}
    return provider


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
