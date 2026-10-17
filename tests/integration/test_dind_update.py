"""End to end container updates, against a docker-in-docker engine, see conftest for fixtures"""

import io
import subprocess
from pathlib import Path

import pytest

from tests.integration.conftest import Dind, Portainer
from tests.lib_test import docker_config, portainer_config
from updates2mqtt.config import NodeConfig
from updates2mqtt.integrations.docker import DockerProvider
from updates2mqtt.integrations.portainer import PortainerClient
from updates2mqtt.model import Discovery

pytestmark = pytest.mark.integration


def analyze(provider: DockerProvider, container_name: str) -> Discovery:
    discovery: Discovery | None = provider.analyze(provider.client.containers.get(container_name), "integration-test")
    assert discovery is not None
    return discovery


def test_update_via_compose(dind_env: Dind, registry: str, tmp_path: Path) -> None:
    ref = f"{registry}/u2m-test/compose-app:latest"
    old_id: str = dind_env.push_image(ref, "1")
    (tmp_path / "compose.yaml").write_text(f"services:\n  app:\n    image: {ref}\n")
    subprocess.run(["docker", "compose", "-p", "u2mcompose", "up", "--detach"], cwd=tmp_path, check=True)
    assert dind_env.container_image_id("u2mcompose-app-1") == old_id

    new_id: str = dind_env.push_image(ref, "2")
    provider = DockerProvider(docker_config(discover_metadata={}), NodeConfig())
    discovery: Discovery = analyze(provider, "u2mcompose-app-1")
    assert discovery.can_restart

    assert provider.update(discovery)
    assert dind_env.container_image_id("u2mcompose-app-1") == new_id


def test_update_via_portainer(dind_env: Dind, registry: str, portainer: Portainer) -> None:
    ref = f"{registry}/u2m-test/portainer-app:latest"
    old_id: str = dind_env.push_image(ref, "1")
    stack_id: int = portainer.create_stack("u2mportainer", f"services:\n  app:\n    image: {ref}\n")
    assert dind_env.container_image_id("u2mportainer-app-1") == old_id

    new_id: str = dind_env.push_image(ref, "2")
    cfg = docker_config(discover_metadata={}, portainer=portainer_config(url=portainer.url, api_key=portainer.api_key))
    provider = DockerProvider(cfg, NodeConfig())
    discovery: Discovery = analyze(provider, "u2mportainer-app-1")
    assert discovery.can_restart
    assert discovery.installation_detail is not None
    assert discovery.installation_detail.portainer_stack_id == str(stack_id)  # type: ignore[attr-defined]

    assert provider.update(discovery)
    assert dind_env.container_image_id("u2mportainer-app-1") == new_id


def test_portainer_redeploy_failure(dind: Dind, portainer: Portainer) -> None:
    """Image only exists locally, so once removed the redeploy fails trying to pull it"""
    ref = "u2m-test/local-only:latest"
    dind.client.images.build(fileobj=io.BytesIO(b"FROM busybox:1.37\nCMD sleep 3600\n"), tag=ref)
    stack_id: int = portainer.create_stack("u2mfailure", f"services:\n  app:\n    image: {ref}\n")
    dind.client.images.remove(ref, force=True)

    client = PortainerClient(portainer_config(url=portainer.url, api_key=portainer.api_key, timeout=60))
    assert not client.redeploy(str(stack_id))
