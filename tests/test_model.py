import json
import time
from collections.abc import AsyncGenerator
from typing import Any

from updates2mqtt.config import NodeConfig, PublishPolicy, Selector, UpdatePolicy
from updates2mqtt.model import Discovery, ReleaseProvider, Selection, timestamp


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


# === Selection Filtering Tests ===


def test_selection_with_no_selector_rules() -> None:
    """When no include/exclude rules, everything should be selected"""
    selector = Selector(include=None, exclude=None)
    selection = Selection(selector, "any-value")
    assert selection.result is True
    assert selection.matched is None


def test_selection_with_none_value_and_no_include() -> None:
    """When value is None and no include rules, should be selected"""
    selector = Selector(include=None, exclude=None)
    selection = Selection(selector, None)
    assert selection.result is True


def test_selection_with_none_value_and_include_rules() -> None:
    """When value is None and include rules exist, should not be selected"""
    selector = Selector(include=["pattern"], exclude=None)
    selection = Selection(selector, None)
    assert selection.result is False


def test_selection_include_matches() -> None:
    """Include rule should match the value"""
    selector = Selector(include=["nginx.*"], exclude=None)
    selection = Selection(selector, "nginx:latest")
    assert selection.result is True
    assert selection.matched == "nginx:latest"


def test_selection_include_no_match() -> None:
    """Include rule should not match if pattern doesn't match"""
    selector = Selector(include=["nginx.*"], exclude=None)
    selection = Selection(selector, "redis:latest")
    assert selection.result is False
    assert selection.matched is None


def test_selection_exclude_matches() -> None:
    """Exclude rule should block matching values"""
    selector = Selector(include=None, exclude=[".*test.*"])
    selection = Selection(selector, "my-test-container")
    assert selection.result is False
    assert selection.matched == "my-test-container"


def test_selection_exclude_no_match() -> None:
    """Exclude rule should allow non-matching values"""
    selector = Selector(include=None, exclude=[".*test.*"])
    selection = Selection(selector, "production-app")
    assert selection.result is True


def test_selection_include_takes_precedence_over_exclude() -> None:
    """When both include and exclude specified, include is evaluated last"""
    # Value matches both include and exclude - include wins (evaluated last)
    selector = Selector(include=["nginx.*"], exclude=[".*latest"])
    selection = Selection(selector, "nginx:latest")
    assert selection.result is True


def test_selection_exclude_blocks_when_include_doesnt_match() -> None:
    """Exclude can block even when include rules exist but don't match"""
    selector = Selector(include=["nginx.*"], exclude=["redis.*"])
    selection = Selection(selector, "redis:latest")
    # First exclude sets result=True (no match), then include sets result=False (no match)
    assert selection.result is False


def test_selection_multiple_include_patterns() -> None:
    """Multiple include patterns - any match should select"""
    selector = Selector(include=["nginx.*", "redis.*", "postgres.*"], exclude=None)

    selection1 = Selection(selector, "nginx:latest")
    assert selection1.result is True

    selection2 = Selection(selector, "redis:7")
    assert selection2.result is True

    selection3 = Selection(selector, "mysql:8")
    assert selection3.result is False


def test_selection_multiple_exclude_patterns() -> None:
    """Multiple exclude patterns - any match should exclude"""
    selector = Selector(include=None, exclude=[".*test.*", ".*dev.*", ".*staging.*"])

    selection1 = Selection(selector, "my-test-app")
    assert selection1.result is False

    selection2 = Selection(selector, "dev-container")
    assert selection2.result is False

    selection3 = Selection(selector, "production-app")
    assert selection3.result is True


def test_selection_regex_special_chars() -> None:
    """Test regex patterns with special characters"""
    selector = Selector(include=[r"ghcr\.io/.*"], exclude=None)
    selection = Selection(selector, "ghcr.io/myorg/myapp")
    assert selection.result is True


def test_selection_bool_conversion() -> None:
    """Selection should be truthy/falsy based on result"""
    selector_allow = Selector(include=None, exclude=None)
    selection_allow = Selection(selector_allow, "test")
    assert bool(selection_allow) is True
    assert selection_allow.result is True

    selector_block = Selector(include=["other"], exclude=None)
    selection_block = Selection(selector_block, "test")
    assert bool(selection_block) is False
    assert selection_block.result is False


# === Discovery check_timestamp Tests ===


def test_discovery_check_timestamp_initial(mock_provider: ReleaseProvider) -> None:
    """New discovery should have check_timestamp set to current time"""
    before = time.time()
    discovery = Discovery(mock_provider, "test", "session1", "node1")
    after = time.time()

    assert discovery.check_timestamp is not None
    assert before <= discovery.check_timestamp <= after
    assert discovery.throttled is False


def test_discovery_check_timestamp_not_throttled_updates(mock_provider: ReleaseProvider) -> None:
    """Non-throttled discovery should update check_timestamp"""
    previous = Discovery(mock_provider, "test", "session1", "node1")
    previous_check_ts = previous.check_timestamp

    time.sleep(0.01)  # Small delay to ensure different timestamp

    current = Discovery(
        mock_provider,
        "test",
        "session2",
        "node1",
        throttled=False,
        previous=previous,
    )

    assert current.check_timestamp is not None
    assert previous_check_ts is not None
    assert current.check_timestamp > previous_check_ts


def test_discovery_check_timestamp_throttled_carries_forward(mock_provider: ReleaseProvider) -> None:
    """Throttled discovery should carry forward previous check_timestamp"""
    previous = Discovery(mock_provider, "test", "session1", "node1")
    previous_check_ts = previous.check_timestamp

    time.sleep(0.01)  # Small delay

    current = Discovery(
        mock_provider,
        "test",
        "session2",
        "node1",
        throttled=True,
        previous=previous,
    )

    assert current.check_timestamp == previous_check_ts
    assert current.throttled is True


def test_discovery_check_timestamp_throttled_without_previous(mock_provider: ReleaseProvider) -> None:
    """Throttled discovery without previous should still set check_timestamp"""
    before = time.time()
    discovery = Discovery(
        mock_provider,
        "test",
        "session1",
        "node1",
        throttled=True,
        previous=None,
    )
    after = time.time()

    # When throttled=True but no previous, the else branch doesn't trigger
    # and check_timestamp keeps its initial value from line 89
    assert discovery.check_timestamp is not None
    assert before <= discovery.check_timestamp <= after


def test_discovery_scan_count_increments(mock_provider: ReleaseProvider) -> None:
    """Scan count should increment with each discovery"""
    d1 = Discovery(mock_provider, "test", "s1", "node1")
    assert d1.scan_count == 1

    d2 = Discovery(mock_provider, "test", "s2", "node1", previous=d1)
    assert d2.scan_count == 2

    d3 = Discovery(mock_provider, "test", "s3", "node1", previous=d2)
    assert d3.scan_count == 3


def test_discovery_first_timestamp_preserved(mock_provider: ReleaseProvider) -> None:
    """First timestamp should be preserved across discoveries"""
    d1 = Discovery(mock_provider, "test", "s1", "node1")
    first_ts = d1.first_timestamp

    time.sleep(0.01)

    d2 = Discovery(mock_provider, "test", "s2", "node1", previous=d1)
    assert d2.first_timestamp == first_ts

    d3 = Discovery(mock_provider, "test", "s3", "node1", previous=d2)
    assert d3.first_timestamp == first_ts


# === Discovery.as_dict() Tests ===


def test_discovery_as_dict_basic_fields(mock_provider: ReleaseProvider) -> None:
    """as_dict should include all basic fields"""
    discovery = Discovery(
        mock_provider,
        "my-container",
        "session123",
        "node001",
        current_version="1.0.0",
        latest_version="2.0.0",
    )
    result = discovery.as_dict()

    assert result["name"] == "my-container"
    assert result["node"] == "node001"
    assert result["installed_version"] == "1.0.0"
    assert result["latest_version"] == "2.0.0"
    assert result["provider"] == {"source_type": "unit_test"}


def test_discovery_as_dict_timestamps(mock_provider: ReleaseProvider) -> None:
    """as_dict should format timestamps correctly"""
    discovery = Discovery(mock_provider, "test", "session1", "node1")
    result = discovery.as_dict()

    assert "first_scan" in result
    assert "timestamp" in result["first_scan"]  # type: ignore[operator]
    assert result["first_scan"]["timestamp"] is not None  # type: ignore[index,call-overload]

    assert "last_scan" in result
    assert "timestamp" in result["last_scan"]  # type: ignore[operator]
    assert "session" in result["last_scan"]  # type: ignore[operator]
    assert result["last_scan"]["session"] == "session1"  # type: ignore[index,call-overload]
    assert result["last_scan"]["throttled"] is False  # type: ignore[index,call-overload]


def test_discovery_as_dict_all_fields(mock_provider: ReleaseProvider) -> None:
    """as_dict should include all fields with correct values"""
    discovery = Discovery(
        mock_provider,
        "full-test",
        "sess1",
        "node1",
        entity_picture_url="https://example.com/logo.png",
        current_version="1.0",
        latest_version="2.0",
        can_update=True,
        can_build=True,
        can_restart=True,
        status="off",
        publish_policy=PublishPolicy.MQTT,
        update_type="Docker",
        release_url="https://github.com/test/releases",
        release_summary="Bug fixes",
        device_icon="mdi:docker",
        custom={"image_ref": "test:latest"},
        features=["INSTALL", "PROGRESS"],
    )
    result = discovery.as_dict()

    assert result["entity_picture_url"] == "https://example.com/logo.png"
    assert result["can_update"] is True
    assert result["can_build"] is True
    assert result["can_restart"] is True
    assert result["status"] == "off"
    assert result["publish_policy"] == "MQTT"
    assert result["update_type"] == "Docker"
    assert result["release_url"] == "https://github.com/test/releases"
    assert result["release_summary"] == "Bug fixes"
    assert result["device_icon"] == "mdi:docker"
    assert result["features"] == ["INSTALL", "PROGRESS"]
    # Custom data is stored under source_type key
    assert result["unit_test"] == {"image_ref": "test:latest"}


def test_discovery_as_dict_update_info(mock_provider: ReleaseProvider) -> None:
    """as_dict should include update info"""
    discovery = Discovery(mock_provider, "test", "session1", "node1")
    discovery.update_last_attempt = 1234567890.0
    result: dict[str, str | list[Any] | dict[str, Any] | int | None] = discovery.as_dict()

    assert "update" in result
    assert result["update"]["in_progress"] is False  # type: ignore[index,call-overload]
    assert result["update"]["last_attempt"] is not None  # type: ignore[index,call-overload]


def test_discovery_as_dict_scan_count(mock_provider: ReleaseProvider) -> None:
    """as_dict should include scan_count"""
    d1 = Discovery(mock_provider, "test", "s1", "node1")
    d2 = Discovery(mock_provider, "test", "s2", "node1", previous=d1)

    result = d2.as_dict()
    assert result["scan_count"] == 2


# === timestamp helper function tests ===


def test_timestamp_with_valid_value() -> None:
    """timestamp() should format valid float to ISO string"""
    ts = time.time()
    result = timestamp(ts)
    assert result is not None
    assert "T" in result  # ISO format has T separator


def test_timestamp_with_none() -> None:
    """timestamp() should return None for None input"""
    result = timestamp(None)
    assert result is None


def test_timestamp_with_invalid_value() -> None:
    """timestamp() should return None for invalid values"""
    # Very large number that can't be converted
    result = timestamp(float("inf"))
    assert result is None
