import json
from collections.abc import AsyncGenerator

from updates2mqtt.config import NodeConfig, UpdatePolicy
from updates2mqtt.model import Discovery, ReleaseProvider


def test_discovery_stringifies(mock_provider: ReleaseProvider) -> None:
    uut = Discovery(mock_provider, "test", "test_session", "tester")
    assert str(uut)


def test_discovery_repr(mock_provider: ReleaseProvider) -> None:
    uut = Discovery(
        mock_provider,
        "my-container",
        "session123",
        "node001",
        current_version="1.0.0",
        latest_version="2.0.0",
    )
    result = repr(uut)
    assert "my-container" in result
    assert "1.0.0" in result
    assert "2.0.0" in result


def test_discovery_defaults(mock_provider: ReleaseProvider) -> None:
    uut = Discovery(mock_provider, "test", "test_session", "tester")
    assert uut.name == "test"
    assert uut.session == "test_session"
    assert uut.node == "tester"
    assert uut.source_type == mock_provider.source_type
    assert uut.can_update is False
    assert uut.can_build is False
    assert uut.can_restart is False
    assert uut.status == "on"
    assert uut.current_version is None
    assert uut.latest_version is None
    assert uut.entity_picture_url is None
    assert uut.release_url is None
    assert uut.custom == {}
    assert uut.features == []


def test_discovery_with_all_fields(mock_provider: ReleaseProvider) -> None:
    previous = Discovery(mock_provider, "full-container", "sess000", "tester")
    previous.update_last_attempt = 1234567890.0
    uut = Discovery(
        mock_provider,
        "full-container",
        "sess001",
        "node002",
        entity_picture_url="https://example.com/logo.png",
        current_version="1.0.0",
        latest_version="2.0.0",
        can_update=True,
        can_build=True,
        can_restart=True,
        status="off",
        update_type="Docker Build",
        update_policy=UpdatePolicy.AUTO,
        release_url="https://github.com/example/releases",
        release_summary="Bug fixes and improvements",
        device_icon="mdi:docker",
        custom={"image_ref": "nginx:latest", "platform": "linux/amd64"},
        features=["INSTALL", "PROGRESS", "RELEASE_NOTES"],
        previous=previous,
    )
    assert uut.name == "full-container"
    assert uut.entity_picture_url == "https://example.com/logo.png"
    assert uut.current_version == "1.0.0"
    assert uut.latest_version == "2.0.0"
    assert uut.can_update is True
    assert uut.can_build is True
    assert uut.can_restart is True
    assert uut.status == "off"
    assert uut.update_type == "Docker Build"
    assert uut.update_policy == UpdatePolicy.AUTO
    assert uut.update_last_attempt == 1234567890.0
    assert uut.release_url == "https://github.com/example/releases"
    assert uut.release_summary == "Bug fixes and improvements"
    assert uut.device_icon == "mdi:docker"
    assert uut.custom["image_ref"] == "nginx:latest"
    assert "INSTALL" in uut.features


def test_discovery_title_from_template(mock_provider: ReleaseProvider) -> None:
    uut = Discovery(
        mock_provider,
        "my-app",
        "sess001",
        "server01",
        update_type="Docker Image",
    )
    assert uut.title == "Docker Image for my-app on server01"


def test_discovery_title_custom_template(mock_provider: ReleaseProvider) -> None:
    uut = Discovery(
        mock_provider,
        "my-app",
        "sess001",
        "server01",
        title_template="Update available: {discovery.name}",
    )
    assert uut.title == "Update available: my-app"


def test_discovery_title_no_template(mock_provider: ReleaseProvider) -> None:
    uut = Discovery(
        mock_provider,
        "my-app",
        "sess001",
        "server01",
        title_template=None,  # type: ignore[arg-type]
    )
    assert uut.title == "my-app"


def test_discovery_str_is_valid_json(mock_provider: ReleaseProvider) -> None:
    uut = Discovery(
        mock_provider,
        "json-test",
        "sess001",
        "node001",
        current_version="1.0",
        custom={"key": "value"},
    )
    result = str(uut)
    parsed = json.loads(result)
    assert parsed["name"] == "json-test"
    assert parsed["current_version"] == "1.0"


def test_release_provider_stop(node_cfg: NodeConfig) -> None:
    # Create a real ReleaseProvider to test stop()
    class TestProvider(ReleaseProvider):
        def update(self, discovery: Discovery) -> bool:  # noqa: ARG002
            return False

        def rescan(self, discovery: Discovery) -> Discovery | None:  # noqa: ARG002
            return None

        async def scan(self, session: str) -> AsyncGenerator[Discovery]:
            yield Discovery(self, "test", session, "node")

        def command(
            self,
            discovery_name: str,  # noqa: ARG002
            command: str,  # noqa: ARG002
            on_update_start: object,  # noqa: ARG002
            on_update_end: object,  # noqa: ARG002
        ) -> bool:
            return False

        def resolve(self, discovery_name: str) -> Discovery | None:  # noqa: ARG002
            return None

    provider = TestProvider(node_cfg, source_type="test_provider")
    assert not provider.stopped.is_set()
    provider.stop()
    assert provider.stopped.is_set()


def test_release_provider_str(node_cfg: NodeConfig) -> None:
    class TestProvider(ReleaseProvider):
        def update(self, discovery: Discovery) -> bool:  # noqa: ARG002
            return False

        def rescan(self, discovery: Discovery) -> Discovery | None:  # noqa: ARG002
            return None

        async def scan(self, session: str) -> AsyncGenerator[Discovery]:
            yield Discovery(self, "test", session, "node")

        def command(
            self,
            discovery_name: str,  # noqa: ARG002
            command: str,  # noqa: ARG002
            on_update_start: object,  # noqa: ARG002
            on_update_end: object,  # noqa: ARG002
        ) -> bool:
            return False

        def resolve(self, discovery_name: str) -> Discovery | None:  # noqa: ARG002
            return None

    provider = TestProvider(node_cfg, source_type="my_source")
    assert str(provider) == "my_source Discovery"
