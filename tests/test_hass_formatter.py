import updates2mqtt
from conftest import Discovery
from updates2mqtt.hass_formatter import hass_format_config


def test_formatter_includes_device(mock_discoveries: list[Discovery], monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(updates2mqtt, "version", "3.0.0")
    msg = hass_format_config(
        mock_discoveries[0],
        "obj001",
        "state_topic_1",
        "command_topic_1",
        force_command_topic=False,
        device_creation=True,
        area="Basement",
    )
    assert msg == {
        "name": "TestRun for thing-1 on testbed01",
        "unique_id": "obj001",
        "update_policy": None,
        "can_build": False,
        "can_restart": False,
        "can_update": True,
        "command_topic": "command_topic_1",
        "state_topic": "state_topic_1",
        "device_class": None,
        "payload_install": "unit_test|thing-1|install",
        "source_session": None,
        "supported_features": [],
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
    msg = hass_format_config(mock_discoveries[0], "obj001", "state_topic_1", "command_topic_1", True, device_creation=False)
    assert msg == {
        "name": "TestRun for thing-1 on testbed01",
        "unique_id": "obj001",
        "update_policy": None,
        "can_build": False,
        "can_restart": False,
        "can_update": True,
        "command_topic": "command_topic_1",
        "state_topic": "state_topic_1",
        "device_class": None,
        "payload_install": "unit_test|thing-1|install",
        "source_session": None,
        "supported_features": [],
        "origin": {
            "name": "testbed01 updates2mqtt",
            "sw_version": "3.0.0",
            "support_url": "https://github.com/rhizomatics/updates2mqtt/issues",
        },
    }


def test_formatter_forces_command_topic(mock_discoveries: list[Discovery]) -> None:
    discovery = mock_discoveries[0]
    discovery.can_update = False
    msg = hass_format_config(discovery, "obj001", "state_topic_1", "command_topic_1", True)
    assert msg["command_topic"] == "command_topic_1"
    assert "payload_install" not in msg


def test_formatter_no_update_suppresses_command_topic(mock_discoveries: list[Discovery]) -> None:
    discovery = mock_discoveries[0]
    discovery.can_update = False
    msg = hass_format_config(discovery, "obj001", "state_topic_1", "command_topic_1", False)
    assert "command_topic" not in msg
    assert "payload_install" not in msg
