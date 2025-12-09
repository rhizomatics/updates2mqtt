import os
import tempfile
import uuid
from collections import namedtuple
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from omegaconf import OmegaConf

from updates2mqtt.config import LogLevel, MqttConfig, PackageUpdateInfo, load_app_config, load_package_info

EXAMPLES_ROOT = "examples"
examples = [str(p.name) for p in Path(EXAMPLES_ROOT).iterdir() if p.name.startswith("config")]


def test_envvar_config(monkeypatch) -> None:  # noqa: ANN001
    with tempfile.TemporaryDirectory() as tmpdir:
        monkeypatch.setenv("MQTT_HOST", "193.11.55.12")
        monkeypatch.setenv("MQTT_USER", "tester")
        monkeypatch.setenv("MQTT_PASS", uuid.uuid4().hex)
        monkeypatch.setenv("MQTT_PORT", "1824")
        conf_path: Path = Path(tmpdir) / "config-test-env.yaml"
        validated_config = load_app_config(conf_path, return_invalid=True)
        assert validated_config is not None
        assert validated_config.node.git_path == "/usr/bin/git"
        assert validated_config.mqtt.port == 1824
        assert validated_config.mqtt.host == "193.11.55.12"
        assert validated_config.mqtt.user == "tester"


@pytest.mark.parametrize("config_name", examples)
def test_config(config_name: str, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("MQTT_USER", "tester")
    monkeypatch.setenv("MQTT_PASS", uuid.uuid4().hex)
    config_path: Path = Path(EXAMPLES_ROOT) / config_name
    validated_config = load_app_config(config_path)
    assert validated_config is not None
    assert validated_config.node.git_path == "/usr/bin/git"


def test_round_trip_config() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        conf_path: Path = Path(tmpdir) / "config-test.yaml"
        generated_config = load_app_config(conf_path, return_invalid=True)
        assert conf_path.exists()
        assert generated_config is not None
        # set mandatory values
        OmegaConf.set_readonly(generated_config, False)  # type: ignore[arg-type]
        generated_config.mqtt = MqttConfig(
            host=generated_config.mqtt.host,
            user="myuser",
            password=uuid.uuid4().hex,
            port=generated_config.mqtt.port,
            topic_root=generated_config.mqtt.topic_root,
        )
        conf_path.write_text(OmegaConf.to_yaml(generated_config))
        reloaded_config = load_app_config(conf_path)
        assert reloaded_config is not None
        assert reloaded_config.mqtt.user == "myuser"


uname: type = namedtuple("uname", ["nodename"])


@patch.dict(
    os.environ,
    {
        "MQTT_HOST": "192.168.3.4",
        "MQTT_PORT": "2883",
        "MQTT_USER": "u2macct",
        "MQTT_PASS": "toosecret123!",
        "U2M_LOG_LEVEL": "WARNING",
        "U2M_AUTOGEN_CONFIG": "0",
    },
)
@patch("os.uname", Mock(return_value=uname("xunit003a")))
def test_env_only_config() -> None:
    generated_config = load_app_config(Path("no_such_dir/no_such_file.yaml"))
    assert generated_config is not None
    assert generated_config.mqtt.host == "192.168.3.4"
    assert generated_config.mqtt.port == 2883
    assert generated_config.mqtt.user == "u2macct"
    assert generated_config.mqtt.password == "toosecret123!"  # noqa: S105
    assert generated_config.node.name == "xunit003a"
    assert generated_config.log.level == LogLevel.WARNING
    assert not Path("no_such_dir").exists()


def test_package_config() -> None:
    validated_pkg_info: dict[str, PackageUpdateInfo] = load_package_info(Path("common_packages.yaml"))
    assert validated_pkg_info is not None
    assert len(validated_pkg_info) > 0
    for pkg_name, pkg in validated_pkg_info.items():
        assert pkg_name
        assert pkg.docker is not None
        assert pkg.docker.image_name
        assert pkg.logo_url or pkg.logo_url is None
        assert pkg.release_notes_url or pkg.release_notes_url is None
