import time
from pathlib import Path
from unittest.mock import patch

import pytest
from docker import DockerClient
from docker.models.containers import Container
from pytest_httpx import HTTPXMock
from pytest_subprocess import FakeProcess  # type: ignore[import-not-found]

import updates2mqtt.integrations.docker as mut
from conftest import build_mock_container
from updates2mqtt.config import DockerPackageUpdateInfo, MetadataSourceConfig
from updates2mqtt.integrations.docker import ContainerCustomization
from updates2mqtt.model import Discovery


async def test_scanner(mock_docker_client: DockerClient) -> None:
    with patch("docker.from_env", return_value=mock_docker_client):
        uut = mut.DockerProvider(mut.DockerConfig(discover_metadata={}), {}, mut.NodeConfig())
        session = "unit_123"
        results: list[Discovery] = [d async for d in uut.scan(session)]

    unchanged: list[Discovery] = [d for d in results if d.current_version == d.latest_version]
    assert len(unchanged) == 1
    assert unchanged[0].entity_picture_url == "https://piccy"
    assert unchanged[0].release_url == "https://release"
    assert unchanged[0].custom["platform"] == "linux/amd64"
    changed = [d for d in results if d.current_version != d.latest_version]
    assert len(changed) == 3


async def test_common_packages(mock_docker_client: DockerClient) -> None:
    with patch("docker.from_env", return_value=mock_docker_client):
        uut = mut.DockerProvider(mut.DockerConfig(discover_metadata={}), {}, mut.NodeConfig())
        uut.common_pkgs = {
            "common_pkg": mut.PackageUpdateInfo(
                docker=DockerPackageUpdateInfo(image_name="common/pkg"),
                logo_url="https://commonhub/pkg/logo",
                release_notes_url="https://commonhub/pkg/logo",
            )
        }
        session = "unit_123"
        results: list[Discovery] = [d async for d in uut.scan(session)]

    common: list[Discovery] = [d for d in results if d.custom["image_ref"] == "common/pkg"]
    assert len(common) == 1
    assert common[0].entity_picture_url == "https://commonhub/pkg/logo"
    assert common[0].release_url == "https://commonhub/pkg/logo"


@pytest.mark.httpx_mock(assert_all_requests_were_expected=False)
def test_discover_metadata(httpx_mock: HTTPXMock, mock_docker_client: DockerClient) -> None:
    httpx_mock.add_response(
        json={
            "data": {
                "repositories": {
                    "linuxserver": [
                        {
                            "name": "mctesty901",
                            "project_logo": "http://logos/mctesty.png",
                            "github_url": "https://github/mctesty/901",
                        }
                    ]
                }
            }
        }
    )
    with patch("docker.from_env", return_value=mock_docker_client):
        uut = mut.DockerProvider(
            mut.DockerConfig(discover_metadata={"linuxserver.io": MetadataSourceConfig(enabled=True, cache_ttl=0)}),
            {},
            mut.NodeConfig(),
        )
        uut.discover_metadata()
    assert "mctesty901" in uut.discovered_pkgs
    pkg = uut.discovered_pkgs["mctesty901"]
    assert pkg.docker is not None
    assert pkg.docker.image_name == "lscr.io/linuxserver/mctesty901"
    assert pkg.logo_url == "http://logos/mctesty.png"
    assert pkg.release_notes_url == "https://github/mctesty/901/releases"


def test_build(mock_docker_client: DockerClient, fake_process: FakeProcess, tmpdir: Path) -> None:
    with patch("docker.from_env", return_value=mock_docker_client):
        uut = mut.DockerProvider(mut.DockerConfig(discover_metadata={}), {}, mut.NodeConfig())
        d = Discovery(uut, "build-test-dummy", "test-123", "node003")
        fake_process.register("docker compose build", returncode=0)
        assert uut.build(d, str(tmpdir))
        fake_process.register("docker compose build", returncode=33)
        assert not uut.build(d, str(tmpdir))


def test_container_customization_default() -> None:
    uut = ContainerCustomization(Container())
    assert uut.update == "PASSIVE"
    assert uut.git_repo_path is None
    assert uut.picture is None
    assert uut.relnotes is None
    assert uut.ignore is False


def test_container_customization_by_label() -> None:
    uut = ContainerCustomization(
        Container(attrs={"Config": {"Labels": {"updates2mqtt.ignore": "true", "updates2mqtt.update": "auto"}}})
    )
    assert uut.update == "AUTO"
    assert uut.git_repo_path is None
    assert uut.picture is None
    assert uut.relnotes is None
    assert uut.ignore is True


def test_container_customization_by_env_var() -> None:
    uut = ContainerCustomization(Container(attrs={"Config": {"Env": {"UPD2MQTT_UPDATE=auto", "UPD2MQTT_IGNORE=true"}}}))
    assert uut.update == "AUTO"
    assert uut.git_repo_path is None
    assert uut.picture is None
    assert uut.relnotes is None
    assert uut.ignore is True


def test_container_customization_label_precedence() -> None:
    uut = ContainerCustomization(
        Container(
            attrs={
                "Config": {
                    "Env": {"UPD2MQTT_UPDATE=passive", "UPD2MQTT_IGNORE=false", "UPD2MQTT_RELNOTES=https://release.me"},
                    "Labels": {
                        "updates2mqtt.ignore": "true",
                        "updates2mqtt.update": "auto",
                        "updates2mqtt.git_repo_path": "./build",
                    },
                }
            }
        )
    )
    assert uut.update == "AUTO"
    assert uut.git_repo_path == "./build"
    assert uut.picture is None
    assert uut.relnotes == "https://release.me"
    assert uut.ignore is True


async def test_scanner_container_version_excluded_by_pattern(mock_docker_client: DockerClient) -> None:
    # Add a container with an include pattern that doesn't match its image
    included_container = build_mock_container("private/internal-app:latest")
    included_container.attrs["Config"]["Env"] = ["UPD2MQTT_VERSION_EXCLUDE=999.*"]  # ty:ignore[not-subscriptable]
    mock_docker_client.containers.list.return_value = [included_container]  # type: ignore[attr-defined]

    with patch("docker.from_env", return_value=mock_docker_client):
        uut = mut.DockerProvider(mut.DockerConfig(discover_metadata={}), {}, mut.NodeConfig())
        session = "unit_123"
        results: list[Discovery] = [d async for d in uut.scan(session)]

    results = [d for d in results if d.custom.get("image_ref") == "private/internal-app:latest"]
    assert len(results) == 1
    assert results[0].custom.get("skip_pull") is True
    assert results[0].custom.get("can_pull") is False
    assert results[0].update_type == "Skipped"


async def test_scanner_container_version_passes_pattern(mock_docker_client: DockerClient) -> None:
    # Add a container with an include pattern that doesn't match its image
    included_container = build_mock_container("private/internal-app:latest")
    included_container.attrs["Config"]["Env"] = ["UPD2MQTT_VERSION_EXCLUDE=.*nightly.*"]  # ty:ignore[not-subscriptable]
    included_container.attrs["Config"]["Env"] = ["UPD2MQTT_VERSION_INCLUDE=999.*999"]  # ty:ignore[not-subscriptable]
    mock_docker_client.containers.list.return_value = [included_container]  # type: ignore[attr-defined]

    with patch("docker.from_env", return_value=mock_docker_client):
        uut = mut.DockerProvider(mut.DockerConfig(discover_metadata={}), {}, mut.NodeConfig())
        session = "unit_123"
        results: list[Discovery] = [d async for d in uut.scan(session)]

    results = [d for d in results if d.custom.get("image_ref") == "private/internal-app:latest"]
    assert len(results) == 1
    assert results[0].custom.get("skip_pull") is False
    assert results[0].custom.get("can_pull") is True
    assert results[0].update_type == "Docker Image"


def test_fetch_pulls_image_when_can_pull(mock_docker_client: DockerClient) -> None:
    from unittest.mock import MagicMock

    with patch("docker.from_env", return_value=mock_docker_client):
        uut = mut.DockerProvider(mut.DockerConfig(discover_metadata={}), {}, mut.NodeConfig())
        discovery = Discovery(
            uut,
            "fetch-test-container",
            "test-session",
            "node001",
            custom={"can_pull": True, "image_ref": "nginx:latest", "platform": "linux/amd64"},
        )

        mock_image = MagicMock()
        mock_image.id = "sha256:abc123"
        mock_docker_client.images.pull.return_value = mock_image  # type: ignore[attr-defined]

        uut.fetch(discovery)

        mock_docker_client.images.pull.assert_called_once_with(  # type: ignore[attr-defined]
            "nginx:latest", platform="linux/amd64", all_tags=False
        )


def test_fetch_skips_pull_when_cannot_pull(mock_docker_client: DockerClient) -> None:
    with patch("docker.from_env", return_value=mock_docker_client):
        uut = mut.DockerProvider(mut.DockerConfig(discover_metadata={}), {}, mut.NodeConfig())
        discovery = Discovery(
            uut,
            "fetch-test-container",
            "test-session",
            "node001",
            custom={"can_pull": False, "image_ref": "nginx:latest"},
        )

        uut.fetch(discovery)

        mock_docker_client.images.pull.assert_not_called()  # type: ignore[attr-defined]


def test_fetch_builds_when_can_build(mock_docker_client: DockerClient, tmpdir: Path) -> None:
    with patch("docker.from_env", return_value=mock_docker_client):
        uut = mut.DockerProvider(mut.DockerConfig(discover_metadata={}), {}, mut.NodeConfig())
        discovery = Discovery(
            uut,
            "build-container",
            "test-session",
            "node001",
            can_build=True,
            custom={
                "can_pull": False,
                "compose_path": str(tmpdir),
                "git_repo_path": ".",
            },
        )

        with (
            patch("updates2mqtt.integrations.docker.git_check_update_available", return_value=False),
            patch.object(uut, "build", return_value=True) as mock_build,
        ):
            uut.fetch(discovery)

            mock_build.assert_called_once_with(discovery, str(tmpdir))
            mock_docker_client.images.pull.assert_not_called()  # type: ignore[attr-defined]


def test_fetch_builds_with_git_pull_when_update_available(mock_docker_client: DockerClient, tmpdir: Path) -> None:
    with patch("docker.from_env", return_value=mock_docker_client):
        uut = mut.DockerProvider(mut.DockerConfig(discover_metadata={}), {}, mut.NodeConfig())
        discovery = Discovery(
            uut,
            "build-container",
            "test-session",
            "node001",
            can_build=True,
            custom={
                "can_pull": False,
                "compose_path": str(tmpdir),
                "git_repo_path": ".",
            },
        )

        with (
            patch("updates2mqtt.integrations.docker.git_check_update_available", return_value=True),
            patch("updates2mqtt.integrations.docker.git_pull") as mock_git_pull,
            patch.object(uut, "build", return_value=True) as mock_build,
        ):
            uut.fetch(discovery)

            mock_git_pull.assert_called_once()
            mock_build.assert_called_once_with(discovery, str(tmpdir))


def test_fetch_skips_build_when_no_compose_path(mock_docker_client: DockerClient) -> None:
    with patch("docker.from_env", return_value=mock_docker_client):
        uut = mut.DockerProvider(mut.DockerConfig(discover_metadata={}), {}, mut.NodeConfig())
        discovery = Discovery(
            uut,
            "build-container",
            "test-session",
            "node001",
            can_build=True,
            custom={
                "can_pull": False,
                "git_repo_path": "/some/repo",
                # no compose_path
            },
        )

        with patch.object(uut, "build") as mock_build:
            uut.fetch(discovery)

            mock_build.assert_not_called()


def test_rescan_returns_updated_discovery(mock_docker_client: DockerClient) -> None:
    from conftest import build_mock_container

    container = build_mock_container("rescan/test:v2")
    container.name = "rescan-test-container"  # type: ignore[misc]
    mock_docker_client.containers.get.return_value = container  # type: ignore[attr-defined]

    with patch("docker.from_env", return_value=mock_docker_client):
        uut = mut.DockerProvider(mut.DockerConfig(discover_metadata={}), {}, mut.NodeConfig())
        original_discovery = Discovery(
            uut,
            "rescan-test-container",
            "test-session",
            "node001",
            current_version="v1",
            update_last_attempt=1234567890.0,
        )

        result = uut.rescan(original_discovery)

        assert result is not None
        assert result.name == "rescan-test-container"
        assert result.session == "test-session"
        # update_last_attempt should be preserved from original discovery
        assert result.update_last_attempt == 1234567890.0
        # Discovery should be stored in provider's discoveries dict
        assert "rescan-test-container" in uut.discoveries


def test_rescan_returns_none_when_container_not_found(mock_docker_client: DockerClient) -> None:
    import docker.errors

    mock_docker_client.containers.get.side_effect = docker.errors.NotFound("Container not found")  # type: ignore[attr-defined]

    with patch("docker.from_env", return_value=mock_docker_client):
        uut = mut.DockerProvider(mut.DockerConfig(discover_metadata={}), {}, mut.NodeConfig())
        discovery = Discovery(uut, "nonexistent-container", "test-session", "node001")

        result = uut.rescan(discovery)

        assert result is None


def test_rescan_returns_none_on_api_error(mock_docker_client: DockerClient) -> None:
    import docker.errors

    mock_docker_client.containers.get.side_effect = docker.errors.APIError("API failure")  # type: ignore[attr-defined]

    with patch("docker.from_env", return_value=mock_docker_client):
        uut = mut.DockerProvider(mut.DockerConfig(discover_metadata={}), {}, mut.NodeConfig())
        discovery = Discovery(uut, "error-container", "test-session", "node001")

        result = uut.rescan(discovery)

        assert result is None


def test_command_install_success(mock_docker_client: DockerClient) -> None:
    from unittest.mock import MagicMock

    from conftest import build_mock_container

    container: Container = build_mock_container("nginx:latest")
    container.name = "test-container"  # type: ignore[misc]
    mock_docker_client.containers.get.return_value = container  # type: ignore[attr-defined]

    with patch("docker.from_env", return_value=mock_docker_client):
        uut = mut.DockerProvider(mut.DockerConfig(discover_metadata={}), {}, mut.NodeConfig())
        discovery = Discovery(
            uut,
            "test-container",
            "test-session",
            "node001",
            can_update=True,
            custom={"can_pull": True, "image_ref": "nginx:latest", "platform": "linux/amd64"},
        )
        uut.discoveries["test-container"] = discovery

        on_start = MagicMock()
        on_end = MagicMock()

        # Mock update to return True (restart succeeded)
        with patch.object(uut, "update", return_value=True):
            result = uut.command("test-container", "install", on_start, on_end)

        assert result is True
        on_start.assert_called_once_with(discovery)
        on_end.assert_called_once()


def test_command_install_update_fails(mock_docker_client: DockerClient) -> None:
    from unittest.mock import MagicMock

    with patch("docker.from_env", return_value=mock_docker_client):
        uut = mut.DockerProvider(mut.DockerConfig(discover_metadata={}), {}, mut.NodeConfig())
        discovery = Discovery(
            uut,
            "test-container",
            "test-session",
            "node001",
            can_update=True,
            custom={"can_pull": True, "image_ref": "nginx:latest"},
        )
        uut.discoveries["test-container"] = discovery

        on_start = MagicMock()
        on_end = MagicMock()

        # Mock update to return False (restart failed)
        with patch.object(uut, "update", return_value=False):
            result = uut.command("test-container", "install", on_start, on_end)

        assert result is False
        on_start.assert_called_once_with(discovery)
        on_end.assert_called_once_with(discovery)


def test_command_unknown_entity(mock_docker_client: DockerClient) -> None:
    from unittest.mock import MagicMock

    with patch("docker.from_env", return_value=mock_docker_client):
        uut = mut.DockerProvider(mut.DockerConfig(discover_metadata={}), {}, mut.NodeConfig())

        on_start = MagicMock()
        on_end = MagicMock()

        result = uut.command("nonexistent-container", "install", on_start, on_end)

        assert result is False
        on_start.assert_not_called()
        on_end.assert_not_called()


def test_command_unknown_command(mock_docker_client: DockerClient) -> None:
    from unittest.mock import MagicMock

    with patch("docker.from_env", return_value=mock_docker_client):
        uut = mut.DockerProvider(mut.DockerConfig(discover_metadata={}), {}, mut.NodeConfig())
        discovery = Discovery(uut, "test-container", "test-session", "node001", can_update=True)
        uut.discoveries["test-container"] = discovery

        on_start = MagicMock()
        on_end = MagicMock()

        result = uut.command("test-container", "unknown-cmd", on_start, on_end)

        assert result is False
        on_start.assert_not_called()
        on_end.assert_not_called()


def test_command_cannot_update(mock_docker_client: DockerClient) -> None:
    from unittest.mock import MagicMock

    with patch("docker.from_env", return_value=mock_docker_client):
        uut = mut.DockerProvider(mut.DockerConfig(discover_metadata={}), {}, mut.NodeConfig())
        discovery = Discovery(uut, "test-container", "test-session", "node001", can_update=False)
        uut.discoveries["test-container"] = discovery

        on_start = MagicMock()
        on_end = MagicMock()

        result = uut.command("test-container", "install", on_start, on_end)

        assert result is False
        on_start.assert_not_called()
        on_end.assert_not_called()


def test_command_handles_exception(mock_docker_client: DockerClient) -> None:
    from unittest.mock import MagicMock

    with patch("docker.from_env", return_value=mock_docker_client):
        uut = mut.DockerProvider(mut.DockerConfig(discover_metadata={}), {}, mut.NodeConfig())
        discovery = Discovery(uut, "test-container", "test-session", "node001", can_update=True)
        uut.discoveries["test-container"] = discovery

        on_start = MagicMock()
        on_end = MagicMock()

        # Mock update to raise an exception
        with patch.object(uut, "update", side_effect=RuntimeError("Something went wrong")):
            result = uut.command("test-container", "install", on_start, on_end)

        assert result is False
        on_start.assert_called_once_with(discovery)
        # on_end should still be called with original discovery on exception
        on_end.assert_called_once_with(discovery)


def test_analyze_throttles_on_429_error(mock_docker_client: DockerClient) -> None:
    from http import HTTPStatus
    from unittest.mock import Mock

    import docker.errors
    from requests import Response

    container = build_mock_container("throttled/image:latest")
    container.name = "throttled-container"  # type: ignore[misc]

    # Create a real APIError with a mock response that has status_code 429
    mock_response = Mock(spec=Response)
    mock_response.status_code = HTTPStatus.TOO_MANY_REQUESTS
    mock_response.reason = "Too Many Requests"
    error_429 = docker.errors.APIError("Rate limit exceeded", response=mock_response, explanation="Rate limit exceeded")

    mock_docker_client.images.get_registry_data.side_effect = error_429  # type: ignore[attr-defined]

    with patch("docker.from_env", return_value=mock_docker_client):
        uut = mut.DockerProvider(mut.DockerConfig(discover_metadata={}), {}, mut.NodeConfig())
        uut.api_throttle_pause = 60  # Set to 60 seconds for test

        # First call should trigger throttling
        result = uut.analyze(container, "test-session")

        assert result is None
        assert uut.pause_api_until is not None
        # assert uut.pause_api_until > time.time()


def test_analyze_skips_during_throttle_period(mock_docker_client: DockerClient) -> None:
    container = build_mock_container("throttled/image:latest")
    container.name = "throttled-container"  # type: ignore[misc]

    with patch("docker.from_env", return_value=mock_docker_client):
        uut = mut.DockerProvider(mut.DockerConfig(discover_metadata={}), {}, mut.NodeConfig())
        # Set throttle to expire in the future
        uut.pause_api_until["docker.io"] = time.time() + 300

        # Should skip analysis during throttle period
        uut.analyze(container, "test-session")

        # Should not have called get_registry_data since we're throttled
        mock_docker_client.images.get_registry_data.assert_not_called()  # type: ignore[attr-defined]


def test_analyze_resumes_after_throttle_expires(mock_docker_client: DockerClient) -> None:
    container = build_mock_container("resumed/image:latest")
    container.name = "resumed-container"  # type: ignore[misc]

    with patch("docker.from_env", return_value=mock_docker_client):
        uut = mut.DockerProvider(mut.DockerConfig(discover_metadata={}), {}, mut.NodeConfig())
        # Set throttle to have already expired
        uut.pause_api_until["docker.io"] = time.time()

        result = uut.analyze(container, "test-session")

        # Throttle should be cleared
        assert "docker.io" not in uut.pause_api_until
        # Should have attempted to get registry data
        mock_docker_client.images.get_registry_data.assert_called()  # type: ignore[attr-defined]
        # Result should be a valid discovery (not None due to throttling)
        assert result is not None
