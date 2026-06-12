from typing import TYPE_CHECKING
from unittest.mock import Mock, patch

import docker
import pytest
from pytest_httpx import HTTPXMock

from updates2mqtt.config import DockerConfig, DockerPackageUpdateInfo, MetadataSourceConfig, PackageUpdateInfo, RegistryConfig
from updates2mqtt.integrations.docker import Throttler
from updates2mqtt.integrations.docker_enrich import (
    DIFF_URL_TEMPLATES,
    REGISTRY_GHCR,
    RELEASE_URL_TEMPLATES,
    SOURCE_PLATFORM_GITHUB,
    CommonPackageEnricher,
    ContainerDistributionAPIVersionLookup,
    DefaultPackageEnricher,
    DockerClientVersionLookup,
    DockerImageInfo,
    LinuxServerIOPackageEnricher,
    PackageEnricher,
    SourceReleaseEnricher,
    id_source_platform,
)
from updates2mqtt.model import VersionPolicy

if TYPE_CHECKING:
    from updates2mqtt.model import ReleaseDetail


def test_docker_image_info_bare_default() -> None:
    uut = DockerImageInfo("test")
    assert uut.index_name == "docker.io"
    assert uut.tag_or_digest == "latest"
    assert uut.tag == "latest"
    assert uut.name == "library/test"
    assert uut.pinned_digest is None
    assert not uut.pinned
    assert uut.untagged_ref == "test"


def test_docker_image_info_non_docker_unqualified() -> None:
    uut = DockerImageInfo("myreg.io/test")
    assert uut.index_name == "myreg.io"
    assert uut.tag_or_digest == "latest"
    assert uut.tag == "latest"
    assert uut.pinned_digest is None
    assert uut.name == "test"
    assert uut.untagged_ref == "myreg.io/test"


def test_docker_image_info_with_tag() -> None:
    uut = DockerImageInfo("test/unit:nightly")
    assert uut.index_name == "docker.io"
    assert uut.tag_or_digest == "nightly"
    assert uut.tag == "nightly"
    assert uut.pinned_digest is None
    assert uut.name == "test/unit"
    assert uut.untagged_ref == "test/unit"


def test_docker_image_info_with_digest_qualifier() -> None:
    uut = DockerImageInfo("test/unit@sha2030:58495945945")
    assert uut.index_name == "docker.io"
    assert uut.tag_or_digest == "sha2030:58495945945"
    assert uut.pinned_digest == "sha2030:58495945945"
    assert uut.tag is None
    assert uut.name == "test/unit"
    assert uut.untagged_ref == "test/unit"


def test_docker_image_info_with_digest() -> None:
    uut = DockerImageInfo("ghcr.io/immich-app/postgres@sha256:41eacbe83eca995561fe43814fd4891e16e39632806253848efaf04d3c8a8b84")
    assert uut.index_name == REGISTRY_GHCR
    assert uut.tag_or_digest == "sha256:41eacbe83eca995561fe43814fd4891e16e39632806253848efaf04d3c8a8b84"
    assert uut.tag is None
    assert uut.pinned_digest == "sha256:41eacbe83eca995561fe43814fd4891e16e39632806253848efaf04d3c8a8b84"
    assert uut.name == "immich-app/postgres"
    assert uut.untagged_ref == "ghcr.io/immich-app/postgres"


def test_docker_image_info_with_pinned_tag() -> None:
    uut = DockerImageInfo(
        "ghcr.io/immich-app/postgres:14-vectorchord0.4.3-pgvectors0.2.0@sha256:41eacbe83eca995561fe43814fd4891e16e39632806253848efaf04d3c8a8b84",
        attributes={
            "RepoDigests": [
                "ghcr.io/immich-app/postgres@sha256:2c496e3b9d476ea723e6f0df05d1f690fed2d79b61f4ed75597679892d86311a",
                "ghcr.io/immich-app/postgres@sha256:41eacbe83eca995561fe43814fd4891e16e39632806253848efaf04d3c8a8b84",
            ]
        },
    )
    assert uut.index_name == REGISTRY_GHCR
    assert uut.tag_or_digest == "sha256:41eacbe83eca995561fe43814fd4891e16e39632806253848efaf04d3c8a8b84"
    assert uut.tag == "14-vectorchord0.4.3-pgvectors0.2.0"
    assert uut.repo_digest is None
    assert uut.repo_digests == [
        "sha256:2c496e3b9d476ea723e6f0df05d1f690fed2d79b61f4ed75597679892d86311a",
        "sha256:41eacbe83eca995561fe43814fd4891e16e39632806253848efaf04d3c8a8b84",
    ]
    assert uut.pinned_digest == "sha256:41eacbe83eca995561fe43814fd4891e16e39632806253848efaf04d3c8a8b84"
    assert uut.pinned
    assert uut.name == "immich-app/postgres"
    assert uut.untagged_ref == "ghcr.io/immich-app/postgres"


def test_docker_image_info_with_pinned_tag_not_pulled() -> None:
    uut = DockerImageInfo(
        "ghcr.io/immich-app/postgres:14-vectorchord0.4.3-pgvectors0.2.0@sha256:41eacbe83eca995561fe43814fd4891e16e39632806253848efaf04d3c8a8b84",
        attributes={
            "RepoDigests": [
                "ghcr.io/immich-app/postgres@sha256:2c496e3b9d476ea723e6f0df05d1f690fed2d79b61f4ed75597679892d86311a"
            ]
        },
    )
    assert uut.index_name == REGISTRY_GHCR
    assert uut.tag_or_digest == "sha256:41eacbe83eca995561fe43814fd4891e16e39632806253848efaf04d3c8a8b84"
    assert uut.tag == "14-vectorchord0.4.3-pgvectors0.2.0"
    assert uut.repo_digest == "sha256:2c496e3b9d476ea723e6f0df05d1f690fed2d79b61f4ed75597679892d86311a"
    assert uut.repo_digests == ["sha256:2c496e3b9d476ea723e6f0df05d1f690fed2d79b61f4ed75597679892d86311a"]
    assert uut.pinned_digest == "sha256:41eacbe83eca995561fe43814fd4891e16e39632806253848efaf04d3c8a8b84"
    assert not uut.pinned
    assert uut.name == "immich-app/postgres"
    assert uut.untagged_ref == "ghcr.io/immich-app/postgres"


def test_docker_image_qualified_repo_ids() -> None:
    uut = DockerImageInfo(
        "test",
        attributes={
            "RepoDigests": [
                "ghcr.io/immich-app/immich-server@sha256:2c496e3b9d476ea723e6f0df05d1f690fed2d79b61f4ed75597679892d86311a",
                "ghcr.io/immich-app/immich-server@sha256:e6a6298e67ae077808fdb7d8d5565955f60b0708191576143fc02d30ab1389d1",
            ]
        },
    )
    assert uut.repo_digest is None
    assert uut.repo_digests == [
        "sha256:2c496e3b9d476ea723e6f0df05d1f690fed2d79b61f4ed75597679892d86311a",
        "sha256:e6a6298e67ae077808fdb7d8d5565955f60b0708191576143fc02d30ab1389d1",
    ]


def test_docker_image_single_repo_id() -> None:
    uut = DockerImageInfo(
        "test", attributes={"RepoDigests": ["docker@sha256:931f63d7100eb6734405d92d8bd9f4aa708c587510e5cc673bb9ac196a3d733f"]}
    )
    assert uut.repo_digest == "sha256:931f63d7100eb6734405d92d8bd9f4aa708c587510e5cc673bb9ac196a3d733f"
    assert uut.repo_digests == ["sha256:931f63d7100eb6734405d92d8bd9f4aa708c587510e5cc673bb9ac196a3d733f"]


def test_common_enricher() -> None:
    uut = CommonPackageEnricher(DockerConfig())
    uut.initialize()

    assert len(uut.pkgs) > 0
    source_repos = 0
    for pkg_name, pkg in uut.pkgs.items():
        assert isinstance(pkg_name, str)
        assert pkg_name
        assert pkg.docker is not None
        image_names = pkg.docker.image_names
        assert image_names
        for image_name in image_names:
            assert isinstance(image_name, str)
            assert image_name
        assert isinstance(pkg.docker.version_policy, VersionPolicy)
        for url in (pkg.logo_url, pkg.release_notes_url, pkg.source_repo_url):
            assert isinstance(url, str | None)
            if url is not None:
                assert url.startswith("https://") or url.startswith("http://")
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
    cfg: DockerConfig = DockerConfig(discover_metadata={"linuxserver.io": MetadataSourceConfig(cache_ttl=0)})
    uut = LinuxServerIOPackageEnricher(cfg)
    uut.initialize()

    assert "mctesty901" in uut.pkgs
    pkg = uut.pkgs["mctesty901"]
    assert pkg.docker is not None
    assert pkg.docker.image_name == "lscr.io/linuxserver/mctesty901"
    assert pkg.logo_url == "http://logos/mctesty.png"
    assert pkg.release_notes_url == "https://github/mctesty/901/releases"


@pytest.mark.slow
def test_label_enricher_ghcr(mock_throttler: Throttler) -> None:
    uut = ContainerDistributionAPIVersionLookup(mock_throttler, RegistryConfig())
    v: DockerImageInfo = uut.lookup(
        DockerImageInfo("ghcr.io/rhizomatics/updates2mqtt:1.6.0", attributes={"Os": "linux", "Architecture": "amd64"})
    )
    assert v.annotations["org.opencontainers.image.documentation"] == "https://updates2mqtt.rhizomatics.org.uk"


@pytest.mark.slow
def test_label_enricher_unqualified_docker(mock_throttler: Throttler) -> None:
    uut = ContainerDistributionAPIVersionLookup(mock_throttler, RegistryConfig())
    v: DockerImageInfo = uut.lookup(DockerImageInfo("docker:cli", attributes={"Os": "linux", "Architecture": "amd64"}))
    assert v.annotations["org.opencontainers.image.url"] == "https://hub.docker.com/_/docker"


@pytest.mark.slow
def test_label_enricher_vanilla_docker(mock_throttler: Throttler) -> None:
    uut = ContainerDistributionAPIVersionLookup(mock_throttler, RegistryConfig())
    v: DockerImageInfo = uut.lookup(DockerImageInfo("jellyfin/jellyfin", attributes={"Os": "linux", "Architecture": "amd64"}))
    assert v.annotations is not None


@pytest.mark.slow
def test_label_enricher_vanilla_docker_v1(mock_throttler: Throttler) -> None:
    uut = DockerClientVersionLookup(docker.from_env(), mock_throttler, RegistryConfig())
    v: DockerImageInfo = uut.lookup(DockerImageInfo("jellyfin/jellyfin", attributes={"Os": "linux", "Architecture": "amd64"}))
    assert v.annotations is not None


@pytest.mark.slow
def test_label_enricher_gitlab(mock_throttler: Throttler) -> None:
    uut = ContainerDistributionAPIVersionLookup(mock_throttler, RegistryConfig())
    v: DockerImageInfo = uut.lookup(
        DockerImageInfo("registry.gitlab.com/elad.bar/dahuavto2mqtt", attributes={"Os": "linux", "Architecture": "amd64"})
    )
    assert v.annotations is not None


def test_id_source_platform() -> None:
    assert id_source_platform("https://my.home.server/repo.git") is None
    assert id_source_platform("https://github.com/immich-app/immich") == SOURCE_PLATFORM_GITHUB


def test_id_source_platform_none_input() -> None:
    """id_source_platform should handle None input"""
    assert id_source_platform(None) is None


def test_id_source_platform_empty_string() -> None:
    """id_source_platform should handle empty string"""
    assert id_source_platform("") is None


def test_id_source_platform_github_variations() -> None:
    """id_source_platform should match various GitHub URL formats"""
    assert id_source_platform("https://github.com/org/repo") == SOURCE_PLATFORM_GITHUB
    assert id_source_platform("https://github.com/org/repo.git") == SOURCE_PLATFORM_GITHUB
    assert id_source_platform("https://github.com/org/repo#branch") == SOURCE_PLATFORM_GITHUB


# === DefaultPackageEnricher Tests ===


def test_default_enricher_returns_package_info() -> None:
    """DefaultPackageEnricher should always return a PackageUpdateInfo"""
    cfg = DockerConfig()
    enricher = DefaultPackageEnricher(cfg)

    result = enricher.enrich(DockerImageInfo(ref="nginx:latest"))

    assert result is not None
    assert result.docker is not None
    assert result.docker.image_name == "nginx"
    assert result.logo_url == cfg.default_entity_picture_url
    assert result.release_notes_url is None


def test_default_enricher_with_none_image_name() -> None:
    """DefaultPackageEnricher should handle None image_name"""
    cfg = DockerConfig()
    enricher = DefaultPackageEnricher(cfg)

    result: PackageUpdateInfo | None = enricher.enrich(DockerImageInfo("image:tag"))

    assert result is not None
    assert result.docker is not None
    assert result.docker.image_name == "image"


# === PackageEnricher Base Tests ===


def test_package_enricher_match_by_image_name() -> None:
    """PackageEnricher.enrich should match by image_name"""
    cfg = DockerConfig()
    enricher = PackageEnricher(cfg)
    enricher.pkgs["test-pkg"] = PackageUpdateInfo(
        docker=DockerPackageUpdateInfo(image_name="test/image"),
        logo_url="https://logo.png",
        release_notes_url="https://notes",
    )

    result = enricher.enrich(DockerImageInfo(ref="test/image:latest"))

    assert result is not None
    assert result.logo_url == "https://logo.png"


def test_package_enricher_match_by_image_ref() -> None:
    """PackageEnricher.enrich should match by image_ref"""
    cfg = DockerConfig()
    enricher = PackageEnricher(cfg)
    enricher.pkgs["test-pkg"] = PackageUpdateInfo(
        docker=DockerPackageUpdateInfo(image_name="ghcr.io/org/app:latest"),
        logo_url="https://logo.png",
    )

    result = enricher.enrich(DockerImageInfo(ref="ghcr.io/org/app:latest"))

    assert result is not None
    assert result.logo_url == "https://logo.png"


def test_package_enricher_no_match() -> None:
    """PackageEnricher.enrich should return None when no match"""
    cfg = DockerConfig()
    enricher = PackageEnricher(cfg)
    enricher.pkgs["other-pkg"] = PackageUpdateInfo(
        docker=DockerPackageUpdateInfo(image_name="other/image"),
    )

    result = enricher.enrich(DockerImageInfo(ref="test/image:latest"))

    assert result is None


# === SourceReleaseEnricher Tests ===


def test_source_release_enricher_basic_annotations() -> None:
    """SourceReleaseEnricher should extract basic OCI annotations"""
    enricher = SourceReleaseEnricher()
    annotations = {
        "org.opencontainers.image.version": "1.2.3",
        "org.opencontainers.image.revision": "abc123def",
    }

    result: ReleaseDetail | None = enricher.enrich(DockerImageInfo("test", annotations=annotations))

    assert result is not None
    assert result.version == "1.2.3"
    assert result.revision == "abc123def"


def test_source_release_enricher_empty_annotations() -> None:
    """SourceReleaseEnricher should handle empty annotations"""
    enricher = SourceReleaseEnricher()

    result: ReleaseDetail | None = enricher.enrich(DockerImageInfo("test"))

    assert result is None


def test_source_release_enricher_github_source() -> None:
    """SourceReleaseEnricher should detect GitHub source platform"""
    enricher = SourceReleaseEnricher()
    annotations = {
        "org.opencontainers.image.source": "https://github.com/myorg/myrepo",
        "org.opencontainers.image.version": "1.0.0",
    }

    result: ReleaseDetail | None = enricher.enrich(DockerImageInfo("test", annotations=annotations))

    assert result is not None
    assert result.source_platform == SOURCE_PLATFORM_GITHUB
    assert result.source_repo_url == "https://github.com/myorg/myrepo"


def test_source_release_enricher_implies_github_source() -> None:
    enricher = SourceReleaseEnricher()
    result: ReleaseDetail | None = enricher.enrich(DockerImageInfo(ref="ghcr.io/rhizomatics/updates2mqtt:latest"))

    assert result is not None
    assert result.source_platform == SOURCE_PLATFORM_GITHUB
    assert result.source_repo_url == "https://github.com/rhizomatics/updates2mqtt"


def test_source_release_enricher_strips_hash_from_source() -> None:
    """SourceReleaseEnricher should strip hash fragment from source URL"""
    enricher = SourceReleaseEnricher()
    annotations = {
        "org.opencontainers.image.source": "https://github.com/myorg/myrepo#branch-name",
    }

    result: ReleaseDetail | None = enricher.enrich(DockerImageInfo("test", annotations=annotations))

    # Source is stored with fragment, but platform detection uses stripped URL
    assert result is not None
    assert result.source_url == "https://github.com/myorg/myrepo#branch-name"
    assert result.source_repo_url == "https://github.com/myorg/myrepo"
    assert result.source_platform == SOURCE_PLATFORM_GITHUB


def test_source_release_enricher_no_known_platform() -> None:
    """SourceReleaseEnricher should not set source_platform for unknown sources"""
    enricher = SourceReleaseEnricher()
    annotations = {
        "org.opencontainers.image.source": "https://gitbadger.com/myorg/myrepo",
    }

    result: ReleaseDetail | None = enricher.enrich(DockerImageInfo("test", annotations=annotations))
    assert result is not None
    assert result.source_platform is None
    assert result.source_url == "https://gitbadger.com/myorg/myrepo"


def test_source_release_enricher_known_other_platform() -> None:
    enricher = SourceReleaseEnricher()
    annotations = {
        "org.opencontainers.image.source": "https://gitlab.com/myorg/myrepo",
    }

    result: ReleaseDetail | None = enricher.enrich(DockerImageInfo("test", annotations=annotations))
    assert result is not None
    assert result.source_platform == "GitLab"
    assert result.source_url == "https://gitlab.com/myorg/myrepo"


def test_source_release_enricher_uses_provided_source_repo_url() -> None:
    """SourceReleaseEnricher should use provided source_repo_url as fallback"""
    enricher = SourceReleaseEnricher()
    annotations: dict[str, str] = {}  # No source in annotations

    result: ReleaseDetail | None = enricher.enrich(
        DockerImageInfo("test", annotations=annotations), source_repo_url="https://github.com/fallback/repo"
    )
    assert result is not None
    assert result.source_platform == SOURCE_PLATFORM_GITHUB


def test_source_release_enricher_uses_provided_release_url() -> None:
    """SourceReleaseEnricher should use provided release_url"""
    enricher = SourceReleaseEnricher()
    annotations = {
        "org.opencontainers.image.source": "https://github.com/myorg/myrepo",
    }

    result: ReleaseDetail | None = enricher.enrich(
        DockerImageInfo("test", annotations=annotations), notes_url="https://custom.release.url"
    )
    assert result is not None
    assert result.notes_url == "https://custom.release.url"


# === URL Template Tests ===


def test_diff_url_template_github() -> None:
    """DIFF_URL_TEMPLATES should generate correct GitHub commit URL"""
    template = DIFF_URL_TEMPLATES[SOURCE_PLATFORM_GITHUB]
    url = template.format(repo="https://github.com/org/repo", revision="abc123")
    assert url == "https://github.com/org/repo/commit/abc123"


def test_release_url_template_github() -> None:
    """RELEASE_URL_TEMPLATES should generate correct GitHub release URL"""
    template = RELEASE_URL_TEMPLATES[SOURCE_PLATFORM_GITHUB]
    url = template.format(repo="https://github.com/org/repo", version="v1.0.0")
    assert url == "https://github.com/org/repo/releases/tag/v1.0.0"


# === LinuxServerIOPackageEnricher Tests ===


def test_linuxserverio_enricher_disabled() -> None:
    """LinuxServerIOPackageEnricher should not fetch if disabled"""
    cfg = DockerConfig()
    cfg.discover_metadata["linuxserver.io"].enabled = False
    enricher = LinuxServerIOPackageEnricher(cfg)
    enricher.initialize()

    assert len(enricher.pkgs) == 0


@pytest.mark.httpx_mock(assert_all_requests_were_expected=False)
def test_linuxserverio_enricher_handles_api_error(httpx_mock: HTTPXMock) -> None:
    """LinuxServerIOPackageEnricher should handle API errors gracefully"""
    httpx_mock.add_response(status_code=500)

    cfg: DockerConfig = DockerConfig(discover_metadata={"linuxserver.io": MetadataSourceConfig(cache_ttl=0)})
    enricher = LinuxServerIOPackageEnricher(cfg)
    enricher.initialize()

    assert len(enricher.pkgs) == 0


@pytest.mark.httpx_mock(assert_all_requests_were_expected=False)
def test_linuxserverio_enricher_handles_empty_response(httpx_mock: HTTPXMock) -> None:
    """LinuxServerIOPackageEnricher should handle empty response"""
    httpx_mock.add_response(json={"data": {"repositories": {"linuxserver": []}}})
    cfg: DockerConfig = DockerConfig(discover_metadata={"linuxserver.io": MetadataSourceConfig(cache_ttl=0)})
    enricher = LinuxServerIOPackageEnricher(cfg)
    enricher.initialize()

    assert len(enricher.pkgs) == 0


def test_linuxserverio_enricher_enriches() -> None:
    cfg = DockerConfig()
    enricher = LinuxServerIOPackageEnricher(cfg)
    enricher.initialize()
    info: PackageUpdateInfo | None = enricher.enrich(DockerImageInfo("lscr.io/linuxserver/homeassistant"))
    assert info is not None
    assert info.release_notes_url == "https://github.com/linuxserver/docker-homeassistant/releases"


# === DockerImageInfo edge cases ===


def test_docker_image_info_invalid_oci_name_logs_warning() -> None:
    """Uppercase letter in non-library image name triggers OCI name warning."""
    # "Upper/MyImage" has uppercase — re.match(OCI_NAME_RE, "Upper/MyImage") fails
    info = DockerImageInfo("docker.io/Upper/MyImage:latest")
    assert info.name is not None  # constructed despite warning


def test_docker_image_info_invalid_oci_tag_logs_warning() -> None:
    """Tag starting with '-' is not valid per OCI_TAG_RE and triggers a warning."""
    info = DockerImageInfo("docker.io/org/image:-badtag")
    assert info.name is not None


def test_docker_image_info_platform_computed_from_attributes() -> None:
    """Platform string is built from Os/Architecture attributes."""
    info = DockerImageInfo(
        "ghcr.io/org/repo:latest",
        attributes={"Os": "linux", "Architecture": "amd64", "RepoDigests": []},
    )
    assert info.platform == "linux/amd64"


def test_docker_image_info_platform_with_variant() -> None:
    info = DockerImageInfo(
        "ghcr.io/org/repo:latest",
        attributes={"Os": "linux", "Architecture": "arm", "Variant": "v7", "RepoDigests": []},
    )
    assert info.platform == "linux/arm/v7"


def test_as_dict_non_minimal_includes_attributes_and_annotations() -> None:
    info = DockerImageInfo("ghcr.io/org/repo:latest", annotations={"label": "value"})
    result = info.as_dict(minimal=False)
    assert "annotations" in result
    assert "attributes" in result
    assert result["annotations"] == {"label": "value"}


def test_condense_digest_exception_returns_none() -> None:
    """Passing a non-string to condense_digest triggers the except branch."""
    info = DockerImageInfo("ghcr.io/org/repo:latest")
    result = info.condense_digest(None)  # type: ignore[arg-type]
    assert result is None


# === ContainerDistributionAPIVersionLookup.fetch_token ===


@patch("updates2mqtt.integrations.docker_enrich.fetch_url")
def test_fetch_token_mcr_no_auth_host_returns_none(mock_fetch: Mock) -> None:
    """MCR registry has auth_host=None so fetch_token returns None without fetching."""
    from updates2mqtt.config import RegistryConfig
    from updates2mqtt.integrations.docker_enrich import ContainerDistributionAPIVersionLookup

    lookup = ContainerDistributionAPIVersionLookup(Mock(), RegistryConfig())
    result = lookup.fetch_token("mcr.microsoft.com", "dotnet/sdk")
    assert result is None
    mock_fetch.assert_not_called()


@patch("updates2mqtt.integrations.docker_enrich.fetch_url")
def test_fetch_token_401_with_www_authenticate_returns_token(mock_fetch: Mock) -> None:
    """401 response with a valid www-authenticate header triggers realm-based token fetch."""
    from updates2mqtt.config import RegistryConfig
    from updates2mqtt.integrations.docker_enrich import ContainerDistributionAPIVersionLookup

    r401 = Mock()
    r401.status_code = 401
    r401.is_success = False
    r401.headers = {"www-authenticate": 'realm="https://auth.example.com",service="example",scope="repository:org/repo:pull"'}

    r200 = Mock()
    r200.is_success = True
    r200.json.return_value = {"token": "secrettoken"}

    mock_fetch.side_effect = [r401, r200]

    lookup = ContainerDistributionAPIVersionLookup(Mock(), RegistryConfig())
    token = lookup.fetch_token("unknown-registry.io", "org/repo")
    assert token == "secrettoken"  # noqa: S105


@patch("updates2mqtt.integrations.docker_enrich.fetch_url")
def test_fetch_token_401_no_www_authenticate_raises(mock_fetch: Mock) -> None:
    """401 with no www-authenticate header raises AuthError."""
    from updates2mqtt.config import RegistryConfig
    from updates2mqtt.integrations.docker_enrich import AuthError, ContainerDistributionAPIVersionLookup

    r401 = Mock()
    r401.status_code = 401
    r401.is_success = False
    r401.headers = {}  # no www-authenticate

    mock_fetch.return_value = r401

    lookup = ContainerDistributionAPIVersionLookup(Mock(), RegistryConfig())
    with pytest.raises(AuthError, match="No www-authenticate"):
        lookup.fetch_token("unknown-registry.io", "org/repo")


@patch("updates2mqtt.integrations.docker_enrich.fetch_url")
def test_fetch_token_404_probe_then_401_with_auth_header(mock_fetch: Mock) -> None:
    """404 on token URL triggers /v2 probe; 401 on probe is then handled via www-authenticate."""
    from updates2mqtt.config import RegistryConfig
    from updates2mqtt.integrations.docker_enrich import ContainerDistributionAPIVersionLookup

    r404 = Mock()
    r404.status_code = 404
    r404.is_success = False

    r401 = Mock()
    r401.status_code = 401
    r401.is_success = False
    r401.headers = {"www-authenticate": 'realm="https://auth.example.com",service="example",scope="repository:org/repo:pull"'}

    r200 = Mock()
    r200.is_success = True
    r200.json.return_value = {"token": "probetoken"}

    mock_fetch.side_effect = [r404, r401, r200]

    lookup = ContainerDistributionAPIVersionLookup(Mock(), RegistryConfig())
    token = lookup.fetch_token("unknown-registry.io", "org/repo")
    assert token == "probetoken"  # noqa: S105
    assert mock_fetch.call_count == 3
