from pathlib import Path
from unittest.mock import patch

import pytest
from docker import DockerClient
from pytest_httpx import HTTPXMock
from pytest_subprocess import FakeProcess  # type: ignore[import-not-found]

import updates2mqtt.integrations.docker as mut
from updates2mqtt.config import DockerPackageUpdateInfo, MetadataSourceConfig
from updates2mqtt.model import Discovery


async def test_scanner(mock_docker_client: DockerClient) -> None:
    with patch("docker.from_env", return_value=mock_docker_client):
        uut = mut.DockerProvider(mut.DockerConfig(discover_metadata={}), mut.UpdateInfoConfig(), mut.NodeConfig())
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
        uut = mut.DockerProvider(mut.DockerConfig(discover_metadata={}), mut.UpdateInfoConfig(), mut.NodeConfig())
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
def test_discover_metadata(httpx_mock: HTTPXMock) -> None:
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
    uut = mut.DockerProvider(
        mut.DockerConfig(discover_metadata={"linuxserver.io": MetadataSourceConfig(enabled=True, cache_ttl=0)}),
        mut.UpdateInfoConfig(),
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
        uut = mut.DockerProvider(mut.DockerConfig(discover_metadata={}), mut.UpdateInfoConfig(), mut.NodeConfig())
        d = Discovery(uut, "build-test-dummy", session="test-123")
        fake_process.register("docker compose build", returncode=0)
        assert uut.build(d, str(tmpdir))
        fake_process.register("docker compose build", returncode=33)
        assert not uut.build(d, str(tmpdir))
