from typing import Any

import updates2mqtt
from conftest import Discovery
from updates2mqtt.hass_formatter import hass_format_config, hass_format_state
from updates2mqtt.model import ReleaseDetail


def test_formatter_includes_device(mock_discoveries: list[Discovery], monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(updates2mqtt, "version", "3.0.0")
    msg = hass_format_config(
        mock_discoveries[0],
        "obj001",
        state_topic="state_topic_1",
        attrs_topic="main_topic",
        command_topic="command_topic_1",
        force_command_topic=False,
        device_creation=True,
        area="Basement",
    )
    assert msg == {
        "name": "TestRun for thing-1 on testbed01",
        "unique_id": "obj001",
        "command_topic": "command_topic_1",
        "state_topic": "state_topic_1",
        "json_attributes_topic": "main_topic",
        "device_class": None,
        "payload_install": "unit_test|thing-1|install",
        "supported_features": ["INSTALL", "PROGRESS"],
        "default_entity_id": "update.testbed01_unit_test_thing-1",
        "origin": {
            "name": "testbed01 updates2mqtt",
            "sw_version": "3.0.0",
            "support_url": "https://github.com/rhizomatics/updates2mqtt/issues",
        },
        "device": {
            "identifiers": ["testbed01.updates2mqtt"],
            "manufacturer": "rhizomatics",
            "name": "testbed01 updates2mqtt",
            "suggested_area": "Basement",
            "sw_version": "3.0.0",
        },
    }


def test_formatter_excludes_device(mock_discoveries: list[Discovery], monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(updates2mqtt, "version", "3.0.0")
    msg: dict[str, Any] = hass_format_config(
        mock_discoveries[0], "obj001", "state_topic_1", "command_topic_1", "main_topic", True, device_creation=False
    )
    assert msg == {
        "name": "TestRun for thing-1 on testbed01",
        "unique_id": "obj001",
        "command_topic": "command_topic_1",
        "state_topic": "state_topic_1",
        "json_attributes_topic": "main_topic",
        "device_class": None,
        "payload_install": "unit_test|thing-1|install",
        "supported_features": ["INSTALL", "PROGRESS"],
        "default_entity_id": "update.testbed01_unit_test_thing-1",
        "origin": {
            "name": "testbed01 updates2mqtt",
            "sw_version": "3.0.0",
            "support_url": "https://github.com/rhizomatics/updates2mqtt/issues",
        },
    }


def test_formatter_forces_command_topic(mock_discoveries: list[Discovery]) -> None:
    discovery = mock_discoveries[0]
    discovery.can_pull = False
    msg = hass_format_config(discovery, "obj001", "state_topic_1", "command_topic_1", "main_topic", True)
    assert msg["command_topic"] == "command_topic_1"
    assert "payload_install" not in msg


def test_formatter_no_update_suppresses_command_topic(mock_discoveries: list[Discovery]) -> None:
    discovery = mock_discoveries[0]
    discovery.can_pull = False
    msg = hass_format_config(discovery, "obj001", "state_topic_1", "command_topic_1", "main_topic", False)
    assert "command_topic" not in msg
    assert "payload_install" not in msg


# === hass_format_config edge cases ===


def test_hass_format_config_no_attrs_topic(mock_discoveries: list[Discovery], monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(updates2mqtt, "version", "3.0.0")
    msg = hass_format_config(
        mock_discoveries[0], "obj001", "state_topic", "cmd_topic", attrs_topic=None, force_command_topic=False
    )
    assert "json_attributes_topic" not in msg


def test_hass_format_config_with_entity_picture(mock_discoveries: list[Discovery], monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(updates2mqtt, "version", "3.0.0")
    discovery = mock_discoveries[0]
    discovery.entity_picture_url = "https://example.com/icon.png"
    msg = hass_format_config(discovery, "obj001", "state_topic", "cmd_topic", "attrs_topic", False)
    assert msg["entity_picture"] == "https://example.com/icon.png"


def test_hass_format_config_with_device_icon(mock_discoveries: list[Discovery], monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(updates2mqtt, "version", "3.0.0")
    discovery = mock_discoveries[0]
    discovery.device_icon = "mdi:docker"
    msg = hass_format_config(discovery, "obj001", "state_topic", "cmd_topic", "attrs_topic", False)
    assert msg["icon"] == "mdi:docker"


# === hass_format_state ===


def test_hass_format_state_no_release_detail(mock_discoveries: list[Discovery]) -> None:
    discovery = mock_discoveries[0]
    discovery.release_detail = None
    state = hass_format_state(discovery)
    assert "release_summary" not in state
    assert "release_url" not in state


def test_hass_format_state_with_summary(mock_discoveries: list[Discovery]) -> None:
    discovery = mock_discoveries[0]
    discovery.release_detail = ReleaseDetail(name="test", summary="These are the release notes")
    state = hass_format_state(discovery)
    assert state["release_summary"] == "These are the release notes"


def test_hass_format_state_truncates_long_summary(mock_discoveries: list[Discovery]) -> None:
    discovery = mock_discoveries[0]
    discovery.release_detail = ReleaseDetail(name="test", summary="A" * 7000)
    state = hass_format_state(discovery, release_summary_max_size=6144)
    assert len(state["release_summary"]) == 6144


def test_hass_format_state_with_notes_url(mock_discoveries: list[Discovery]) -> None:
    discovery = mock_discoveries[0]
    discovery.release_detail = ReleaseDetail(name="test", notes_url="https://github.com/org/repo/releases/v1.0")
    state = hass_format_state(discovery)
    assert state["release_url"] == "https://github.com/org/repo/releases/v1.0"
