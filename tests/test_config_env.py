from unittest.mock import patch

from updates2mqtt.config import unrecognised_env_vars, warn_unrecognised_env_vars


def test_unrecognised_env_vars() -> None:
    environ = {
        "UPDATES2MQTT_CHECK_INTERVAL": "7200",
        "UPDATES2MQTT_ALLOW_UPDATES": "true",
        "U2M_LOG_LEVEL": "DEBUG",
        "U2M_REMOVE_OLD_IMAGES": "true",
        "MQTT_HOST": "broker",
    }
    assert unrecognised_env_vars(environ) == [
        "U2M_REMOVE_OLD_IMAGES",
        "UPDATES2MQTT_ALLOW_UPDATES",
        "UPDATES2MQTT_CHECK_INTERVAL",
    ]


def test_warn_unrecognised_env_vars() -> None:
    with patch("updates2mqtt.config.log") as mock_log:
        warn_unrecognised_env_vars({"UPDATES2MQTT_CONTAINERS": "all", "U2M_AUTOGEN_CONFIG": "1"})
    assert [c.kwargs["env_var"] for c in mock_log.warning.call_args_list] == ["UPDATES2MQTT_CONTAINERS"]
