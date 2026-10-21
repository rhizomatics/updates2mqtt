"""Smoke test of the published Docker image, built from the Dockerfile and run inside the dind engine

Catches packaging problems unit tests can't see, e.g. a dependency or data file missing from the image
"""

import uuid
from collections.abc import Generator
from pathlib import Path

import docker
import docker.errors
import pytest
from docker.models.containers import Container
from docker.models.networks import Network

from tests.integration.conftest import Dind, wait_for

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).parents[2]
IMAGE_TAG = "updates2mqtt:smoke-test"
MOSQUITTO_IMAGE = "eclipse-mosquitto:2"
NODE_NAME = "smoke-test"
BUILD_TIMEOUT = 900


@pytest.fixture(scope="module")
def image(dind: Dind) -> str:
    # build streams progress, but apt steps can go quiet for longer than the default 60s timeout
    client = docker.DockerClient(base_url=dind.docker_host, timeout=BUILD_TIMEOUT)
    try:
        client.images.build(path=str(REPO_ROOT), tag=IMAGE_TAG, rm=True)
    except docker.errors.BuildError as e:
        log = "".join(str(chunk.get("stream", chunk.get("error", ""))) for chunk in e.build_log)
        pytest.fail(f"Image build failed: {e}\n{log}")
    finally:
        client.close()
    return IMAGE_TAG


@pytest.fixture
def app_container(dind: Dind, image: str) -> Generator[Container]:
    """App container with a broker on a private network, and the dind engine's socket as a real deployment would"""
    suffix: str = uuid.uuid4().hex[:8]
    broker_name: str = f"u2m-smoke-broker-{suffix}"
    network: Network = dind.client.networks.create(f"u2m-smoke-{suffix}")
    containers: list[Container] = []
    try:
        broker: Container = dind.client.containers.run(
            MOSQUITTO_IMAGE,
            ["mosquitto", "-c", "/mosquitto-no-auth.conf"],
            name=broker_name,
            detach=True,
            network=network.name,
        )
        containers.append(broker)
        app: Container = dind.client.containers.run(
            image,
            name=f"u2m-smoke-app-{suffix}",
            detach=True,
            network=network.name,
            environment={
                "MQTT_HOST": broker_name,
                "MQTT_USER": "smoke",
                "MQTT_PASS": "smoke",  # nosec
                "NODE_NAME": NODE_NAME,
            },
            volumes={"/var/run/docker.sock": {"bind": "/var/run/docker.sock", "mode": "rw"}},
        )
        containers.append(app)
        yield app
    finally:
        for c in containers:
            c.remove(force=True, v=True)
        network.remove()


def test_image_starts_and_heartbeats(app_container: Container) -> None:
    topic: str = f"healthcheck/{NODE_NAME}/updates2mqtt"

    def healthy() -> bool:
        app_container.reload()
        if app_container.status != "running":
            pytest.fail(f"App container {app_container.status}:\n{app_container.logs().decode()}")
        exit_code, _ = app_container.exec_run(["/app/healthcheck.sh", topic])
        return exit_code == 0

    try:
        wait_for(healthy, "app heartbeat")
    except TimeoutError:
        pytest.fail(f"No heartbeat on {topic}:\n{app_container.logs().decode()}")
