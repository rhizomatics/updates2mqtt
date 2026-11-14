import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

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


def test_heartbeat_file_default_and_env_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from omegaconf import OmegaConf

    from updates2mqtt.config import HealthCheckConfig

    monkeypatch.delenv("U2M_HEARTBEAT_FILE", raising=False)
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    tempfile.tempdir = None  # gettempdir caches, so pick up TMPDIR
    try:
        assert OmegaConf.structured(HealthCheckConfig).heartbeat_file == str(tmp_path / "updates2mqtt.heartbeat")
    finally:
        tempfile.tempdir = None

    monkeypatch.setenv("U2M_HEARTBEAT_FILE", "/run/u2m/heartbeat")
    assert OmegaConf.structured(HealthCheckConfig).heartbeat_file == "/run/u2m/heartbeat"
    assert unrecognised_env_vars({"U2M_HEARTBEAT_FILE": "/run/u2m/heartbeat"}) == []
