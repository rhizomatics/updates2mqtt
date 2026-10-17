"""Docker-in-docker fixtures, so integration tests run against a real but disposable Docker engine

Only run with `pytest --integration`, and skipped if no local Docker engine is running. Images pulled
inside the dind engine are kept in a named volume, so later runs don't download them again.
"""

import io
import json
import os
import re
import tempfile
import time
import uuid
from collections.abc import Callable, Generator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import docker
import docker.errors
import httpx
import pytest
from docker.models.containers import Container

from updates2mqtt.integrations.portainer import PORTAINER_STACK_STATUS_DEPLOYING

DIND_IMAGE = "docker:dind"
DIND_CACHE_VOLUME = "u2m-test-dind-cache"
DIND_LABEL = "u2m-test"
REGISTRY_PORT = 5000
PORTAINER_PORT = 9000
PORTAINER_PASSWORD = "u2m-test-password"  # nosec
# override with comma separated list, e.g. PORTAINER_TEST_VERSIONS=2.45.0
PORTAINER_VERSIONS = os.environ.get("PORTAINER_TEST_VERSIONS", "2.45.0,2.39.0").split(",")
BASE_IMAGE = "busybox:1.37"
STARTUP_TIMEOUT = 60


def wait_for(check: Callable[[], bool], what: str, timeout: float = STARTUP_TIMEOUT) -> None:
    deadline: float = time.monotonic() + timeout
    while True:
        try:
            if check():
                return
        except (docker.errors.DockerException, httpx.HTTPError):
            pass
        if time.monotonic() >= deadline:
            raise TimeoutError(f"{what} not ready after {timeout}s")
        time.sleep(0.5)


@dataclass
class Dind:
    """Docker engine running inside a container on the local Docker engine"""

    container: Container
    docker_host: str
    client: docker.DockerClient

    def host_url(self, port: int) -> str:
        """URL on the local machine for a port published by a container inside the dind engine"""
        self.container.reload()
        binding = self.container.attrs["NetworkSettings"]["Ports"][f"{port}/tcp"][0]
        return f"http://{binding['HostIp']}:{binding['HostPort']}"

    def push_image(self, ref: str, version: str) -> str:
        """Build a distinct image for `version`, push it to `ref`, and return its id"""
        dockerfile = f'FROM {BASE_IMAGE}\nLABEL u2m.test.version="{version}"\nCMD ["sleep", "3600"]\n'
        image, _ = self.client.images.build(fileobj=io.BytesIO(dockerfile.encode()), tag=ref, rm=True)
        self.client.images.push(ref)
        return str(image.id)

    def container_image_id(self, name: str) -> str:
        return str(self.client.containers.get(name).attrs["Image"])


# Credential helper that never has credentials, the message is what docker treats as not found
NO_CREDENTIALS_HELPER = """#!/bin/sh
case "$1" in
  get) echo "credentials not found in native keychain"; exit 1 ;;
  list) echo "{}" ;;
  *) cat > /dev/null ;;
esac
"""


@pytest.fixture(scope="session")
def isolated_docker_config() -> Generator[None]:
    """Docker config that keeps the user's credential store out of pulls and pushes, e.g. macOS keychain

    An empty config isn't enough, since the docker CLI falls back to a platform credential store when none set
    """
    user_config_dir = Path(os.environ.get("DOCKER_CONFIG", Path.home() / ".docker"))
    with tempfile.TemporaryDirectory() as config_dir, pytest.MonkeyPatch.context() as mp:
        helper = Path(config_dir) / "docker-credential-u2mtest"
        helper.write_text(NO_CREDENTIALS_HELPER)
        helper.chmod(0o700)
        config = {"credsStore": "u2mtest", "cliPluginsExtraDirs": [str(user_config_dir / "cli-plugins")]}
        (Path(config_dir) / "config.json").write_text(json.dumps(config))
        mp.setenv("DOCKER_CONFIG", config_dir)
        mp.setenv("PATH", f"{config_dir}{os.pathsep}{os.environ['PATH']}")
        yield


@pytest.fixture(scope="session")
def dind(isolated_docker_config: None) -> Generator[Dind]:
    try:
        host: docker.DockerClient = docker.from_env()
        host.ping()
    except docker.errors.DockerException as e:
        pytest.skip(f"No local Docker engine running: {e}")

    container: Container = host.containers.run(
        DIND_IMAGE,
        name=f"u2m-test-dind-{uuid.uuid4().hex[:8]}",
        detach=True,
        privileged=True,
        environment={"DOCKER_TLS_CERTDIR": ""},
        # random host ports, only on loopback since the engine is unauthenticated
        ports=cast("Any", {"2375/tcp": ("127.0.0.1", None), f"{PORTAINER_PORT}/tcp": ("127.0.0.1", None)}),
        volumes={DIND_CACHE_VOLUME: {"bind": "/var/lib/docker", "mode": "rw"}},
        labels={DIND_LABEL: "dind"},
    )
    try:
        container.reload()
        binding = container.attrs["NetworkSettings"]["Ports"]["2375/tcp"][0]
        docker_host = f"tcp://{binding['HostIp']}:{binding['HostPort']}"
        # client connects on creation, so can't be made until the engine is up
        wait_for(lambda: bool(docker.DockerClient(base_url=docker_host).ping()), "dind engine")
        client = docker.DockerClient(base_url=docker_host)
        # cache volume may hold containers from an aborted earlier run
        for leftover in client.containers.list(all=True):
            leftover.remove(force=True, v=True)
        client.images.pull(BASE_IMAGE)
        yield Dind(container, docker_host, client)
    finally:
        container.remove(force=True)


@pytest.fixture(scope="session")
def registry(dind: Dind) -> str:
    """Registry inside the dind engine, with image refs resolvable by that engine as localhost"""
    dind.client.containers.run("registry:2", name="registry", detach=True, ports={"5000/tcp": REGISTRY_PORT})
    wait_for(lambda: dind.client.containers.get("registry").status == "running", "registry")
    return f"localhost:{REGISTRY_PORT}"


@pytest.fixture
def dind_env(dind: Dind, monkeypatch: pytest.MonkeyPatch) -> Dind:
    """Point docker.from_env() and the docker CLI at the dind engine"""
    monkeypatch.setenv("DOCKER_HOST", dind.docker_host)
    monkeypatch.delenv("DOCKER_CONTEXT", raising=False)
    return dind


@dataclass
class Portainer:
    version: str
    url: str
    api_key: str
    endpoint_id: int

    def api(self) -> httpx.Client:
        return httpx.Client(base_url=self.url, headers={"X-API-Key": self.api_key}, timeout=60)

    def create_stack(self, name: str, compose: str) -> int:
        with self.api() as client:
            response = client.post(
                "/api/stacks/create/standalone/string",
                params={"endpointId": self.endpoint_id},
                json={"Name": name, "StackFileContent": compose, "Env": []},
            )
            response.raise_for_status()
            stack_id = int(response.json()["Id"])
        # creation may also be asynchronous, from Portainer 2.41
        wait_for(lambda: self.stack(stack_id).get("Status") != PORTAINER_STACK_STATUS_DEPLOYING, f"stack {name} deploy")
        return stack_id

    def stack(self, stack_id: int) -> dict[str, Any]:
        with self.api() as client:
            response = client.get(f"/api/stacks/{stack_id}")
            response.raise_for_status()
            return cast("dict[str, Any]", response.json())


@pytest.fixture(scope="session", params=PORTAINER_VERSIONS)
def portainer(request: pytest.FixtureRequest, dind: Dind) -> Generator[Portainer]:
    """Portainer CE inside the dind engine, managing that engine through its socket"""
    version: str = request.param
    container: Container = dind.client.containers.run(
        f"portainer/portainer-ce:{version}",
        name=f"portainer-{version}",
        detach=True,
        ports={f"{PORTAINER_PORT}/tcp": PORTAINER_PORT},
        volumes={"/var/run/docker.sock": {"bind": "/var/run/docker.sock", "mode": "rw"}},
    )
    try:
        url: str = dind.host_url(PORTAINER_PORT)
        wait_for(lambda: httpx.get(f"{url}/api/system/status").is_success, f"Portainer {version}")
        with httpx.Client(base_url=url, timeout=30) as client:
            # newer versions only allow admin setup with the token logged at startup
            setup_token = re.search(r"setup_token=([0-9a-f]+)", container.logs().decode())
            headers = {"X-Setup-Token": setup_token.group(1)} if setup_token else {}
            credentials = {"Username": "admin", "Password": PORTAINER_PASSWORD}
            client.post("/api/users/admin/init", json=credentials, headers=headers).raise_for_status()
            response = client.post("/api/auth", json=credentials)
            response.raise_for_status()
            client.headers["Authorization"] = f"Bearer {response.json()['jwt']}"
            # cookie authenticated requests need a CSRF token, bearer ones don't
            client.cookies.clear()
            response = client.post("/api/endpoints", data={"Name": "local", "EndpointCreationType": "1"})
            response.raise_for_status()
            endpoint_id = int(response.json()["Id"])
            response = client.post("/api/users/1/tokens", json={"description": "u2m-test", "password": PORTAINER_PASSWORD})
            response.raise_for_status()
            yield Portainer(version, url, response.json()["rawAPIKey"], endpoint_id)
    finally:
        # stacks are left running, remove everything except the shared registry
        for c in dind.client.containers.list(all=True):
            if c.name != "registry":
                c.remove(force=True, v=True)
