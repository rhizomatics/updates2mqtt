import pytest
from pytest_httpx import HTTPXMock

from updates2mqtt.config import DockerConfig
from updates2mqtt.integrations.docker_enrich import CommonPackageEnricher, LabelEnricher, LinuxServerIOPackageEnricher


def test_common_enricher() -> None:
    uut = CommonPackageEnricher(DockerConfig())
    uut.initialize()

    assert len(uut.pkgs) > 0
    for pkg_name, pkg in uut.pkgs.items():
        assert pkg_name
        assert pkg.docker is not None
        assert pkg.docker.image_name
        assert pkg.logo_url or pkg.logo_url is None
        assert pkg.release_notes_url or pkg.release_notes_url is None


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
    manifest = uut.fetch_manifest("ghcr.io/rhizomatics/updates2mqtt:1.6.0", "linux", "amd64")
    assert manifest is not None
    assert manifest["mediaType"] == "application/vnd.oci.image.manifest.v1+json"
    assert manifest["annotations"]["org.opencontainers.image.documentation"] == "https://updates2mqtt.rhizomatics.org.uk"


@pytest.mark.slow
def test_label_enricher_unqualified_docker() -> None:
    uut = LabelEnricher()
    manifest = uut.fetch_manifest("docker:cli", "linux", "amd64")
    assert manifest is not None
    assert manifest["mediaType"] == "application/vnd.oci.image.manifest.v1+json"
    assert manifest["annotations"]["org.opencontainers.image.url"] == "https://hub.docker.com/_/docker"


@pytest.mark.slow
def test_label_enricher_vanilla_docker() -> None:
    uut = LabelEnricher()
    manifest = uut.fetch_manifest("jellyfin/jellyfin", "linux", "amd64")
    assert manifest is not None
    assert manifest["mediaType"] == "application/vnd.docker.distribution.manifest.v2+json"
    assert "config" in manifest
    assert "layers" in manifest
