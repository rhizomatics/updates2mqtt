import pytest
from pytest_httpx import HTTPXMock

from updates2mqtt.config import DockerConfig
from updates2mqtt.integrations.docker_enrich import (
    SOURCE_PLATFORM_GITHUB,
    CommonPackageEnricher,
    LabelEnricher,
    LinuxServerIOPackageEnricher,
    id_source_platform,
)


def test_common_enricher() -> None:
    uut = CommonPackageEnricher(DockerConfig())
    uut.initialize()

    assert len(uut.pkgs) > 0
    source_repos = 0
    for pkg_name, pkg in uut.pkgs.items():
        assert pkg_name
        assert pkg.docker is not None
        assert pkg.docker.image_name
        assert pkg.logo_url or pkg.logo_url is None
        assert pkg.release_notes_url or pkg.release_notes_url is None
        assert pkg.source_repo_url or pkg.source_repo_url is None
        if pkg.source_repo_url:
            source_repos += 1
    assert source_repos > 0


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
    uut = LinuxServerIOPackageEnricher(DockerConfig())
    uut.initialize()

    assert "mctesty901" in uut.pkgs
    pkg = uut.pkgs["mctesty901"]
    assert pkg.docker is not None
    assert pkg.docker.image_name == "lscr.io/linuxserver/mctesty901"
    assert pkg.logo_url == "http://logos/mctesty.png"
    assert pkg.release_notes_url == "https://github/mctesty/901/releases"


@pytest.mark.slow
def test_label_enricher_ghcr() -> None:
    uut = LabelEnricher()
    manifest = uut.fetch_annotations("ghcr.io/rhizomatics/updates2mqtt:1.6.0", "linux", "amd64")
    assert manifest["org.opencontainers.image.documentation"] == "https://updates2mqtt.rhizomatics.org.uk"


@pytest.mark.slow
def test_label_enricher_unqualified_docker() -> None:
    uut = LabelEnricher()
    manifest = uut.fetch_annotations("docker:cli", "linux", "amd64")
    assert manifest["org.opencontainers.image.url"] == "https://hub.docker.com/_/docker"


@pytest.mark.slow
def test_label_enricher_vanilla_docker() -> None:
    uut = LabelEnricher()
    annotations = uut.fetch_annotations("jellyfin/jellyfin", "linux", "amd64")
    assert annotations is not None


def test_id_source_platform() -> None:
    assert id_source_platform("https://my.home.server/repo.git") is None
    assert id_source_platform("https://github.com/immich-app/immich") == SOURCE_PLATFORM_GITHUB
