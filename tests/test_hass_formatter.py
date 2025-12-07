import updates2mqtt
from conftest import Discovery
from updates2mqtt.hass_formatter import hass_format_config


def test_formatter_includes_device(mock_discoveries: list[Discovery], monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(updates2mqtt, "version", "3.0.0")
    msg = hass_format_config(mock_discoveries[0], "obj001", "testbed01", "state_topic_1", "command_topic_1", area="Basement")
    assert msg == {
        "name": "thing-1 unit_test",
        "unique_id": "obj001",
        "update_policy": None,
        "can_build": False,
        "can_restart": False,
        "can_update": False,
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
    msg = hass_format_config(
        mock_discoveries[0], "obj001", "testbed01", "state_topic_1", "command_topic_1", device_creation=False
    )
    assert msg == {
        "name": "thing-1 unit_test on testbed01",
        "unique_id": "obj001",
        "update_policy": None,
        "can_build": False,
        "can_restart": False,
        "can_update": False,
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
