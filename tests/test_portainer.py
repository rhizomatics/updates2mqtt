import json
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from docker import DockerClient
from pytest_httpx import HTTPXMock

import updates2mqtt.integrations.docker as mut
from tests.lib_test import build_mock_container, docker_config, portainer_config
from updates2mqtt.config import NodeConfig, PortainerConfig
from updates2mqtt.integrations.docker_enrich import DockerImageInfo, DockerServiceDetails
from updates2mqtt.integrations.portainer import PortainerClient, is_portainer_image
from updates2mqtt.model import Discovery

PORTAINER_URL = "https://portainer.test:9443"
ENV = [{"name": "TZ", "value": "Europe/London"}]


def portainer_cfg() -> PortainerConfig:
    return portainer_config(url=PORTAINER_URL, api_key="ptr_secret")


def stack(git: bool = False, stack_type: int = 2) -> dict:
    return {
        "Id": 52,
        "Name": "keycloak",
        "Type": stack_type,
        "EndpointId": 3,
        "Env": ENV,
        "GitConfig": {"ReferenceName": "refs/heads/main", "Authentication": None} if git else None,
    }


def test_redeploy_web_editor_stack(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=f"{PORTAINER_URL}/api/stacks/52", method="GET", json=stack())
    httpx_mock.add_response(url=f"{PORTAINER_URL}/api/stacks/52/file", method="GET", json={"StackFileContent": "services: {}"})
    httpx_mock.add_response(url=f"{PORTAINER_URL}/api/stacks/52?endpointId=3", method="PUT", json=stack())

    assert PortainerClient(portainer_cfg()).redeploy("52")

    put: httpx.Request = httpx_mock.get_requests(method="PUT")[0]
    assert put.headers["X-API-Key"] == "ptr_secret"
    assert json.loads(put.content) == {
        "stackFileContent": "services: {}",
        "env": ENV,
        "prune": False,
        "pullImage": False,
    }


def test_redeploy_git_stack(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=f"{PORTAINER_URL}/api/stacks/52", method="GET", json=stack(git=True))
    httpx_mock.add_response(url=f"{PORTAINER_URL}/api/stacks/52/git/redeploy?endpointId=3", method="PUT", json={})

    assert PortainerClient(portainer_cfg()).redeploy("52")

    put: httpx.Request = httpx_mock.get_requests(method="PUT")[0]
    assert json.loads(put.content) == {
        "env": ENV,
        "prune": False,
        "pullImage": False,
        "repositoryReferenceName": "refs/heads/main",
        "repositoryAuthentication": False,
    }


def test_redeploy_refuses_non_compose_stack(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=f"{PORTAINER_URL}/api/stacks/52", method="GET", json=stack(stack_type=1))
    assert not PortainerClient(portainer_cfg()).redeploy("52")
    assert not httpx_mock.get_requests(method="PUT")


def test_redeploy_api_error(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=f"{PORTAINER_URL}/api/stacks/52", method="GET", status_code=403, text="denied")
    assert not PortainerClient(portainer_cfg()).redeploy("52")


def test_redeploy_unreachable(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_exception(httpx.ConnectError("refused"))
    assert not PortainerClient(portainer_cfg()).redeploy("52")


def test_enabled_needs_url_and_key() -> None:
    assert PortainerClient(portainer_cfg()).enabled
    assert not PortainerClient(portainer_config(url=PORTAINER_URL, api_key=None)).enabled
    assert not PortainerClient(portainer_config(url=None, api_key=None)).enabled


def test_config_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PORTAINER_URL", PORTAINER_URL)
    monkeypatch.setenv("PORTAINER_API_KEY", "ptr_env")
    cfg = portainer_config()
    assert cfg.url == PORTAINER_URL
    assert cfg.api_key == "ptr_env"
    assert cfg.verify_ssl
    assert cfg.ca_certs is None


def test_ssl_config_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PORTAINER_VERIFY_SSL", "False")
    monkeypatch.setenv("PORTAINER_CA_CERTS", "/certs/root_ca.pem")
    cfg = portainer_config()
    assert not cfg.verify_ssl
    assert cfg.ca_certs == "/certs/root_ca.pem"


def test_ssl_verify() -> None:
    assert PortainerClient(portainer_cfg()).ssl_verify() is True
    assert PortainerClient(portainer_config(url=PORTAINER_URL, api_key="k", verify_ssl=False)).ssl_verify() is False
    with patch("updates2mqtt.integrations.portainer.ssl.create_default_context") as ctx:
        verify = PortainerClient(portainer_config(url=PORTAINER_URL, api_key="k", ca_certs="/certs/ca.pem")).ssl_verify()
    ctx.assert_called_once_with(cafile="/certs/ca.pem")
    assert verify is ctx.return_value


def test_redeploy_missing_ca_certs() -> None:
    cfg = portainer_config(url=PORTAINER_URL, api_key="k", ca_certs="/nonexistent/ca.pem")
    assert not PortainerClient(cfg).redeploy("52")


@pytest.mark.parametrize(
    ("ref", "expected"),
    [
        ("portainer/portainer-ce:2.21.0", True),
        ("portainer/agent:latest", True),
        ("quay.io/keycloak/keycloak:latest", False),
        (None, False),
    ],
)
def test_is_portainer_image(ref: str | None, expected: bool) -> None:
    assert is_portainer_image(ref) == expected


def test_analyze_can_restart_portainer_stack_when_configured(mock_docker_client: DockerClient) -> None:
    container = build_mock_container("quay.io/keycloak/keycloak:latest")
    container.labels["com.docker.compose.project.working_dir"] = "/data/compose/52"

    with patch("docker.from_env", return_value=mock_docker_client):
        uut = mut.DockerProvider(docker_config(discover_metadata={}, portainer=portainer_cfg()), NodeConfig())
        result = uut.analyze(container, "test-session")

    assert result is not None
    assert result.can_restart is True


def test_analyze_cannot_restart_portainer_itself(mock_docker_client: DockerClient) -> None:
    container = build_mock_container("portainer/portainer-ce:2.21.0")
    container.labels["com.docker.compose.project.working_dir"] = "/data/compose/7"

    with patch("docker.from_env", return_value=mock_docker_client):
        uut = mut.DockerProvider(docker_config(discover_metadata={}, portainer=portainer_cfg()), NodeConfig())
        result = uut.analyze(container, "test-session")

    assert result is not None
    assert result.can_restart is False


def test_url_without_key_disables_portainer(mock_docker_client: DockerClient) -> None:
    with patch("docker.from_env", return_value=mock_docker_client):
        uut = mut.DockerProvider(
            docker_config(discover_metadata={}, portainer=portainer_config(url=PORTAINER_URL, api_key=None)), NodeConfig()
        )
    assert uut.portainer is None


def test_restart_uses_portainer_for_stack(mock_docker_client: DockerClient) -> None:
    with patch("docker.from_env", return_value=mock_docker_client):
        uut = mut.DockerProvider(docker_config(discover_metadata={}, portainer=portainer_cfg()), NodeConfig())
    d = Discovery(
        uut,
        "keycloak",
        "test-123",
        "node003",
        current_detail=DockerImageInfo("quay.io/keycloak/keycloak:latest"),
        installation_detail=DockerServiceDetails(compose_path="/data/compose/52", compose_service="keycloak"),
    )
    with (
        patch.object(PortainerClient, "redeploy", return_value=True) as mock_redeploy,
        patch.object(uut, "execute_compose") as mock_compose,
    ):
        assert uut.restart(d)
    mock_redeploy.assert_called_once_with("52")
    mock_compose.assert_not_called()


def test_restart_prefers_compose_when_path_visible(mock_docker_client: DockerClient, tmp_path: Path) -> None:
    with patch("docker.from_env", return_value=mock_docker_client):
        uut = mut.DockerProvider(docker_config(discover_metadata={}, portainer=portainer_cfg()), NodeConfig())
    d = Discovery(
        uut,
        "keycloak",
        "test-123",
        "node003",
        installation_detail=DockerServiceDetails(compose_path=str(tmp_path), compose_service="keycloak"),
    )
    with (
        patch.object(PortainerClient, "redeploy") as mock_redeploy,
        patch.object(uut, "execute_compose", return_value=True) as mock_compose,
    ):
        assert uut.restart(d)
    mock_redeploy.assert_not_called()
    mock_compose.assert_called_once()
