import tempfile
import uuid
from pathlib import Path

import pytest
from omegaconf import OmegaConf

from updates2mqtt.config import MqttConfig, load_app_config, load_package_info

EXAMPLES_ROOT = "examples"
examples = [str(p.name) for p in Path(EXAMPLES_ROOT).iterdir() if p.name.startswith("config")]


@pytest.mark.parametrize("config_name", examples)
def test_config(config_name: str) -> None:
    config_path: Path = Path(EXAMPLES_ROOT) / config_name
    validated_config = load_app_config(config_path)
    assert validated_config is not None
    assert validated_config.node.git_path == "/usr/bin/git"


def test_round_trip_config() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        conf_path: Path = Path(tmpdir) / "config-test.yaml"
        generated_config = load_app_config(conf_path, return_new=True)
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


def test_package_config() -> None:
    validated_pkg_info = load_package_info(Path("common_packages.yaml"))
    assert validated_pkg_info is not None
    assert len(validated_pkg_info.common_packages) > 0
