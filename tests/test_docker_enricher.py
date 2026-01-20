import pytest
from pytest_httpx import HTTPXMock

from updates2mqtt.config import DockerConfig, DockerPackageUpdateInfo, PackageUpdateInfo
from updates2mqtt.integrations.docker_enrich import (
    DIFF_URL_TEMPLATES,
    RELEASE_URL_TEMPLATES,
    SOURCE_PLATFORM_GITHUB,
    CommonPackageEnricher,
    DefaultPackageEnricher,
    LabelEnricher,
    LinuxServerIOPackageEnricher,
    PackageEnricher,
    SourceReleaseEnricher,
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


@pytest.mark.slow
def test_label_enricher_custom_url() -> None:
    uut = LabelEnricher()
    annotations = uut.fetch_annotations("registry.gitlab.com/elad.bar/dahuavto2mqtt", "linux", "amd64")
    assert annotations is not None


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

    result = enricher.enrich("nginx", "nginx:latest", enricher.log)

    assert result is not None
    assert result.docker is not None
    assert result.docker.image_name == "nginx"
    assert result.logo_url == cfg.default_entity_picture_url
    assert result.release_notes_url is None


def test_default_enricher_with_none_image_name() -> None:
    """DefaultPackageEnricher should handle None image_name"""
    cfg = DockerConfig()
    enricher = DefaultPackageEnricher(cfg)

    result = enricher.enrich(None, "image:tag", enricher.log)

    assert result is not None
    assert result.docker is not None
    assert result.docker.image_name == "UNKNOWN"


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

    result = enricher.enrich("test/image", "test/image:latest", enricher.log)

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

    result = enricher.enrich("some-name", "ghcr.io/org/app:latest", enricher.log)

    assert result is not None
    assert result.logo_url == "https://logo.png"


def test_package_enricher_no_match() -> None:
    """PackageEnricher.enrich should return None when no match"""
    cfg = DockerConfig()
    enricher = PackageEnricher(cfg)
    enricher.pkgs["other-pkg"] = PackageUpdateInfo(
        docker=DockerPackageUpdateInfo(image_name="other/image"),
    )

    result = enricher.enrich("test/image", "test/image:latest", enricher.log)

    assert result is None


def test_package_enricher_none_inputs() -> None:
    """PackageEnricher.enrich should return None for None inputs"""
    cfg = DockerConfig()
    enricher = PackageEnricher(cfg)

    assert enricher.enrich(None, None, enricher.log) is None
    assert enricher.enrich("name", None, enricher.log) is None
    assert enricher.enrich(None, "ref", enricher.log) is None


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

    result = enricher.enrich(annotations)

    assert result["latest_image_created"] == "2024-01-15T10:00:00Z"
    assert result["documentation_url"] == "https://docs.example.com"
    assert result["description"] == "A test image"
    assert result["vendor"] == "Test Vendor"
    assert result["latest_image_version"] == "1.2.3"
    assert result["latest_release_revision"] == "abc123def"


def test_source_release_enricher_empty_annotations() -> None:
    """SourceReleaseEnricher should handle empty annotations"""
    enricher = SourceReleaseEnricher()

    result = enricher.enrich({})

    assert result == {}


def test_source_release_enricher_github_source() -> None:
    """SourceReleaseEnricher should detect GitHub source platform"""
    enricher = SourceReleaseEnricher()
    annotations = {
        "org.opencontainers.image.source": "https://github.com/myorg/myrepo",
        "org.opencontainers.image.version": "1.0.0",
    }

    result = enricher.enrich(annotations)

    assert result.get("source_platform") == SOURCE_PLATFORM_GITHUB
    assert result.get("source") == "https://github.com/myorg/myrepo"


def test_source_release_enricher_strips_hash_from_source() -> None:
    """SourceReleaseEnricher should strip hash fragment from source URL"""
    enricher = SourceReleaseEnricher()
    annotations = {
        "org.opencontainers.image.source": "https://github.com/myorg/myrepo#branch-name",
    }

    result = enricher.enrich(annotations)

    # Source is stored with fragment, but platform detection uses stripped URL
    assert result.get("source") == "https://github.com/myorg/myrepo#branch-name"
    assert result.get("source_platform") == SOURCE_PLATFORM_GITHUB


def test_source_release_enricher_no_known_platform() -> None:
    """SourceReleaseEnricher should not set source_platform for unknown sources"""
    enricher = SourceReleaseEnricher()
    annotations = {
        "org.opencontainers.image.source": "https://gitlab.com/myorg/myrepo",
    }

    result = enricher.enrich(annotations)

    assert "source_platform" not in result
    assert result.get("source") == "https://gitlab.com/myorg/myrepo"


def test_source_release_enricher_uses_provided_source_repo_url() -> None:
    """SourceReleaseEnricher should use provided source_repo_url as fallback"""
    enricher = SourceReleaseEnricher()
    annotations: dict[str, str] = {}  # No source in annotations

    result = enricher.enrich(annotations, source_repo_url="https://github.com/fallback/repo")

    assert result.get("source") == "https://github.com/fallback/repo"
    assert result.get("source_platform") == SOURCE_PLATFORM_GITHUB


def test_source_release_enricher_uses_provided_release_url() -> None:
    """SourceReleaseEnricher should use provided release_url"""
    enricher = SourceReleaseEnricher()
    annotations = {
        "org.opencontainers.image.source": "https://github.com/myorg/myrepo",
    }

    result = enricher.enrich(annotations, release_url="https://custom.release.url")

    assert result.get("release_url") == "https://custom.release.url"


def test_source_release_enricher_record_helper() -> None:
    """SourceReleaseEnricher.record should only add non-None values"""
    enricher = SourceReleaseEnricher()
    results: dict[str, str] = {}

    enricher.record(results, "key1", "value1")
    enricher.record(results, "key2", None)

    assert results == {"key1": "value1"}
    assert "key2" not in results


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
