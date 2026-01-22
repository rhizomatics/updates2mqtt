import docker
import pytest
from pytest_httpx import HTTPXMock

from updates2mqtt.config import DockerConfig, DockerPackageUpdateInfo, PackageUpdateInfo
from updates2mqtt.integrations.docker import Throttler
from updates2mqtt.integrations.docker_enrich import (
    DIFF_URL_TEMPLATES,
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
    assert uut.index_name == "ghcr.io"
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
    assert uut.index_name == "ghcr.io"
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
    assert uut.index_name == "ghcr.io"
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
def test_label_enricher_ghcr(mock_throttler: Throttler) -> None:
    uut = ContainerDistributionAPIVersionLookup(mock_throttler)
    v: DockerImageInfo = uut.lookup(
        DockerImageInfo("ghcr.io/rhizomatics/updates2mqtt:1.6.0", attributes={"Os": "linux", "Architecture": "amd64"})
    )
    assert v.annotations["org.opencontainers.image.documentation"] == "https://updates2mqtt.rhizomatics.org.uk"


@pytest.mark.slow
def test_label_enricher_unqualified_docker(mock_throttler: Throttler) -> None:
    uut = ContainerDistributionAPIVersionLookup(mock_throttler)
    v: DockerImageInfo = uut.lookup(DockerImageInfo("docker:cli", attributes={"Os": "linux", "Architecture": "amd64"}))
    assert v.annotations["org.opencontainers.image.url"] == "https://hub.docker.com/_/docker"


@pytest.mark.slow
def test_label_enricher_vanilla_docker(mock_throttler: Throttler) -> None:
    uut = ContainerDistributionAPIVersionLookup(mock_throttler)
    v: DockerImageInfo = uut.lookup(DockerImageInfo("jellyfin/jellyfin", attributes={"Os": "linux", "Architecture": "amd64"}))
    assert v.annotations is not None


@pytest.mark.slow
def test_label_enricher_vanilla_docker_v1(mock_throttler: Throttler) -> None:
    uut = DockerClientVersionLookup(docker.from_env(), mock_throttler)
    v: DockerImageInfo = uut.lookup(DockerImageInfo("jellyfin/jellyfin", attributes={"Os": "linux", "Architecture": "amd64"}))
    assert v.annotations is not None


@pytest.mark.slow
def test_label_enricher_gitlab(mock_throttler: Throttler) -> None:
    uut = ContainerDistributionAPIVersionLookup(mock_throttler)
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
        "org.opencontainers.image.created": "2024-01-15T10:00:00Z",
        "org.opencontainers.image.documentation": "https://docs.example.com",
        "org.opencontainers.image.description": "A test image",
        "org.opencontainers.image.vendor": "Test Vendor",
        "org.opencontainers.image.version": "1.2.3",
        "org.opencontainers.image.revision": "abc123def",
    }

    result = enricher.enrich(DockerImageInfo("test", annotations=annotations))

    assert result["latest_image_created"] == "2024-01-15T10:00:00Z"
    assert result["documentation_url"] == "https://docs.example.com"
    assert result["description"] == "A test image"
    assert result["vendor"] == "Test Vendor"
    assert result["latest_image_version"] == "1.2.3"
    assert result["latest_image_revision"] == "abc123def"


def test_source_release_enricher_empty_annotations() -> None:
    """SourceReleaseEnricher should handle empty annotations"""
    enricher = SourceReleaseEnricher()

    result = enricher.enrich(DockerImageInfo("test"))

    assert result == {}


def test_source_release_enricher_github_source() -> None:
    """SourceReleaseEnricher should detect GitHub source platform"""
    enricher = SourceReleaseEnricher()
    annotations = {
        "org.opencontainers.image.source": "https://github.com/myorg/myrepo",
        "org.opencontainers.image.version": "1.0.0",
    }

    result = enricher.enrich(DockerImageInfo("test", annotations=annotations))

    assert result.get("source_platform") == SOURCE_PLATFORM_GITHUB
    assert result.get("source") == "https://github.com/myorg/myrepo"


def test_source_release_enricher_strips_hash_from_source() -> None:
    """SourceReleaseEnricher should strip hash fragment from source URL"""
    enricher = SourceReleaseEnricher()
    annotations = {
        "org.opencontainers.image.source": "https://github.com/myorg/myrepo#branch-name",
    }

    result = enricher.enrich(DockerImageInfo("test", annotations=annotations))

    # Source is stored with fragment, but platform detection uses stripped URL
    assert result.get("source") == "https://github.com/myorg/myrepo#branch-name"
    assert result.get("source_platform") == SOURCE_PLATFORM_GITHUB


def test_source_release_enricher_no_known_platform() -> None:
    """SourceReleaseEnricher should not set source_platform for unknown sources"""
    enricher = SourceReleaseEnricher()
    annotations = {
        "org.opencontainers.image.source": "https://gitlab.com/myorg/myrepo",
    }

    result = enricher.enrich(DockerImageInfo("test", annotations=annotations))

    assert "source_platform" not in result
    assert result.get("source") == "https://gitlab.com/myorg/myrepo"


def test_source_release_enricher_uses_provided_source_repo_url() -> None:
    """SourceReleaseEnricher should use provided source_repo_url as fallback"""
    enricher = SourceReleaseEnricher()
    annotations: dict[str, str] = {}  # No source in annotations

    result = enricher.enrich(
        DockerImageInfo("test", annotations=annotations), source_repo_url="https://github.com/fallback/repo"
    )

    assert result.get("source_platform") == SOURCE_PLATFORM_GITHUB


def test_source_release_enricher_uses_provided_release_url() -> None:
    """SourceReleaseEnricher should use provided release_url"""
    enricher = SourceReleaseEnricher()
    annotations = {
        "org.opencontainers.image.source": "https://github.com/myorg/myrepo",
    }

    result = enricher.enrich(DockerImageInfo("test", annotations=annotations), release_url="https://custom.release.url")

    assert result.get("release_url") == "https://custom.release.url"


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
    cfg = DockerConfig()
    enricher = LinuxServerIOPackageEnricher(cfg)
    enricher.initialize()

    assert len(enricher.pkgs) == 0


@pytest.mark.httpx_mock(assert_all_requests_were_expected=False)
def test_linuxserverio_enricher_handles_empty_response(httpx_mock: HTTPXMock) -> None:
    """LinuxServerIOPackageEnricher should handle empty response"""
    httpx_mock.add_response(json={"data": {"repositories": {"linuxserver": []}}})
    cfg = DockerConfig()
    enricher = LinuxServerIOPackageEnricher(cfg)
    enricher.initialize()

    assert len(enricher.pkgs) == 0
