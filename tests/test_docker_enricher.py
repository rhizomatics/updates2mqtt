from collections import defaultdict
from typing import TYPE_CHECKING, Any
from unittest.mock import Mock

import docker
import httpx
import pytest
import yaml
from pytest_httpx import HTTPXMock

from tests.lib_test import docker_config
from tests.oci.fake_registry import FakeRegistry
from updates2mqtt.config import (
    PKG_INFO_FILE,
    SOURCE_PLATFORM_GITHUB,
    DockerConfig,
    DockerPackageUpdateInfo,
    MetadataSourceConfig,
    PackageUpdateInfo,
    RegistryConfig,
    VersionPolicy,
    docker_image_names,
)
from updates2mqtt.helpers import APIStatsCounter, Throttler
from updates2mqtt.integrations.docker_enrich import (
    DIFF_URL_TEMPLATES,
    HOTIO_PAGE_URL,
    HOTIO_SITE_TREE_URL,
    REGISTRY_GHCR,
    RELEASE_URL_TEMPLATES,
    CachingRegistryTransport,
    CommonPackageEnricher,
    ContainerDistributionAPIVersionLookup,
    DefaultPackageEnricher,
    DockerClientVersionLookup,
    DockerImageInfo,
    HotioPackageEnricher,
    LinuxServerIOPackageEnricher,
    PackageEnricher,
    SourceReleaseEnricher,
    id_source_platform,
    registry_cache_ttl,
)
from updates2mqtt.oci import Credentials, DockerConfigCredentials, HttpRequest, StaticCredentials
from updates2mqtt.oci import media_types as mt

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
    uut = CommonPackageEnricher(docker_config())
    uut.initialize()

    assert len(uut.pkgs) > 0
    source_repos = 0
    for pkg_name, pkg in uut.pkgs.items():
        assert isinstance(pkg_name, str)
        assert pkg_name
        assert pkg.docker is not None
        image_names = docker_image_names(pkg.docker)
        assert image_names
        for image_name in image_names:
            assert isinstance(image_name, str)
            assert image_name
        assert isinstance(pkg.docker.version_policy, VersionPolicy)
        for url in (pkg.logo_url, pkg.release_notes_url, pkg.source_repo_url):
            assert isinstance(url, str | None)
            if url is not None:
                assert url.startswith(("https://", "http://"))
        if pkg.source_repo_url:
            source_repos += 1
    assert source_repos > 0


class _DuplicateKeyLoader(yaml.SafeLoader):
    """SafeLoader variant that rejects duplicate mapping keys, which PyYAML otherwise silently overwrites."""


def _construct_mapping_no_duplicates(loader: yaml.SafeLoader, node: yaml.Node) -> dict[Any, Any]:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node)
        if key in mapping:
            raise ValueError(f"Duplicate key {key!r} in {PKG_INFO_FILE}")
        mapping[key] = loader.construct_object(value_node)
    return mapping


_DuplicateKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping_no_duplicates)


def test_common_packages_yaml_no_duplicate_keys() -> None:
    with PKG_INFO_FILE.open() as f:
        raw = yaml.load(f, Loader=_DuplicateKeyLoader)

    assert raw["common_packages"]


def test_common_packages_yaml_unique_image_names() -> None:
    uut = CommonPackageEnricher(docker_config())
    uut.initialize()

    owners: dict[str, list[str]] = defaultdict(list)
    for pkg_name, pkg in uut.pkgs.items():
        assert pkg.docker is not None
        for image_name in docker_image_names(pkg.docker):
            owners[image_name].append(pkg_name)

    duplicates = {image_name: pkg_names for image_name, pkg_names in owners.items() if len(pkg_names) > 1}
    assert not duplicates, f"docker image names must map to exactly one common package: {duplicates}"


def test_docker_image_names_single_string() -> None:
    assert docker_image_names(DockerPackageUpdateInfo(image_name="foo/bar")) == ["foo/bar"]


def test_docker_image_names_list() -> None:
    assert docker_image_names(DockerPackageUpdateInfo(image_name=["foo/bar", "baz/qux"])) == ["foo/bar", "baz/qux"]


def test_package_enricher_matches_any_image_name_in_list() -> None:
    pkgs = {
        "multi": PackageUpdateInfo(
            docker=DockerPackageUpdateInfo(image_name=["foo/bar", "baz/qux"]),
            logo_url="https://example/logo",
        )
    }
    uut = PackageEnricher(docker_config(), pkgs)

    assert uut.enrich(DockerImageInfo("foo/bar")) is pkgs["multi"]
    assert uut.enrich(DockerImageInfo("baz/qux")) is pkgs["multi"]
    assert uut.enrich(DockerImageInfo("other/image")) is None


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
    cfg: DockerConfig = docker_config(discover_metadata={"linuxserver.io": MetadataSourceConfig(cache_ttl=0)})
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
    cfg = docker_config()
    enricher = DefaultPackageEnricher(cfg)

    result = enricher.enrich(DockerImageInfo(ref="nginx:latest"))

    assert result is not None
    assert result.docker is not None
    assert result.docker.image_name == "nginx"
    assert result.logo_url == cfg.default_entity_picture_url
    assert result.release_notes_url is None


def test_default_enricher_with_none_image_name() -> None:
    """DefaultPackageEnricher should handle None image_name"""
    cfg = docker_config()
    enricher = DefaultPackageEnricher(cfg)

    result: PackageUpdateInfo | None = enricher.enrich(DockerImageInfo("image:tag"))

    assert result is not None
    assert result.docker is not None
    assert result.docker.image_name == "image"


# === PackageEnricher Base Tests ===


def test_package_enricher_match_by_image_name() -> None:
    """PackageEnricher.enrich should match by image_name"""
    cfg = docker_config()
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
    cfg = docker_config()
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
    cfg = docker_config()
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
    cfg = docker_config()
    cfg.discover_metadata["linuxserver.io"].enabled = False
    enricher = LinuxServerIOPackageEnricher(cfg)
    enricher.initialize()

    assert len(enricher.pkgs) == 0


@pytest.mark.httpx_mock(assert_all_requests_were_expected=False)
def test_linuxserverio_enricher_handles_api_error(httpx_mock: HTTPXMock) -> None:
    """LinuxServerIOPackageEnricher should handle API errors gracefully"""
    httpx_mock.add_response(status_code=500)

    cfg: DockerConfig = docker_config(discover_metadata={"linuxserver.io": MetadataSourceConfig(cache_ttl=0)})
    enricher = LinuxServerIOPackageEnricher(cfg)
    enricher.initialize()

    assert len(enricher.pkgs) == 0


@pytest.mark.httpx_mock(assert_all_requests_were_expected=False)
def test_linuxserverio_enricher_handles_empty_response(httpx_mock: HTTPXMock) -> None:
    """LinuxServerIOPackageEnricher should handle empty response"""
    httpx_mock.add_response(json={"data": {"repositories": {"linuxserver": []}}})
    cfg: DockerConfig = docker_config(discover_metadata={"linuxserver.io": MetadataSourceConfig(cache_ttl=0)})
    enricher = LinuxServerIOPackageEnricher(cfg)
    enricher.initialize()

    assert len(enricher.pkgs) == 0


def test_linuxserverio_enricher_enriches() -> None:
    cfg = docker_config()
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
    result = info.condense_digest(None)
    assert result is None


# === ContainerDistributionAPIVersionLookup, over the OCI client ===

FAKE_REGISTRY = "registry.example"


def _local_image(ref: str = f"{FAKE_REGISTRY}/szabis/iventoy:latest", **attributes: Any) -> DockerImageInfo:
    return DockerImageInfo(
        ref,
        attributes={
            "Os": "linux",
            "Architecture": "amd64",
            "RepoDigests": ["szabis/iventoy@sha256:24eb769a52ec27284804fbf2a55526fefe197eb14dbd8076b1b15a036a6aa8b6"],
            **attributes,
        },
    )


def _throttler() -> Mock:
    return Mock(spec=Throttler, check_throttle=Mock(return_value=False))


def _lookup(fake: FakeRegistry, throttler: Mock | None = None, **kwargs: Any) -> ContainerDistributionAPIVersionLookup:
    return ContainerDistributionAPIVersionLookup(
        throttler or _throttler(), RegistryConfig(), credentials=StaticCredentials({}), transport=fake.transport(), **kwargs
    )


def _image(fake: FakeRegistry, media_type: str = mt.OCI_MANIFEST, config_media_type: str = mt.OCI_CONFIG) -> tuple[str, str]:
    """Platform manifest, untagged, returns manifest and config digests"""
    config_digest: str = fake.add_blob(
        {
            "architecture": "amd64",
            "os": "linux",
            "created": "2026-09-01T00:00:00Z",
            "config": {"Labels": {"org.opencontainers.image.version": "1.0.43"}},
        }
    )
    manifest_digest: str = fake.add_manifest(
        "szabis/iventoy",
        {
            "schemaVersion": 2,
            "mediaType": media_type,
            "config": {"mediaType": config_media_type, "digest": config_digest, "size": 1234},
            "layers": [],
        },
    )
    return manifest_digest, config_digest


def _index(fake: FakeRegistry, manifest_digest: str, arch: str = "amd64") -> str:
    return fake.add_manifest(
        "szabis/iventoy",
        {
            "schemaVersion": 2,
            "mediaType": mt.OCI_INDEX,
            "manifests": [
                {"mediaType": mt.OCI_MANIFEST, "digest": manifest_digest, "platform": {"os": "linux", "architecture": arch}}
            ],
            "annotations": {"org.opencontainers.image.source": "https://github.com/szabis/iventoy"},
        },
        tag="latest",
    )


def test_lookup_multi_platform_index() -> None:
    fake = FakeRegistry()
    manifest_digest, config_digest = _image(fake)
    index_digest: str = _index(fake, manifest_digest)

    result = _lookup(fake).lookup(_local_image())

    assert result.image_digest == index_digest
    assert result.short_digest == index_digest[7:19]
    assert result.repo_digest == config_digest
    assert result.created == "2026-09-01T00:00:00Z"
    assert result.annotations["org.opencontainers.image.version"] == "1.0.43"
    assert result.annotations["org.opencontainers.image.source"] == "https://github.com/szabis/iventoy"
    assert result.version == "1.0.43"
    assert result.origin == "OCI_V2"
    assert result.error is None


@pytest.mark.parametrize(
    ("media_type", "config_media_type"),
    [(mt.DOCKER_MANIFEST, mt.DOCKER_CONFIG), (mt.OCI_MANIFEST, mt.OCI_CONFIG)],
)
def test_lookup_single_platform_manifest_without_index(media_type: str, config_media_type: str) -> None:
    """Issue #175 - registry returns the image manifest directly where no index published"""
    fake = FakeRegistry()
    manifest_digest, config_digest = _image(fake, media_type, config_media_type)
    fake.manifests["szabis/iventoy", "latest"] = fake.manifests["szabis/iventoy", manifest_digest]

    result = _lookup(fake).lookup(_local_image())

    assert result.image_digest == manifest_digest
    assert result.repo_digest == config_digest
    assert result.version == "1.0.43"


def test_lookup_minimal_skips_config() -> None:
    fake = FakeRegistry()
    manifest_digest, config_digest = _image(fake)
    _index(fake, manifest_digest)

    result = _lookup(fake).lookup(_local_image(), minimal=True)

    assert result.repo_digest == config_digest
    assert result.version is None
    assert result.origin == "OCI_V2_MINIMAL"
    assert not any("/blobs/" in r.path for r in fake.requests)


def test_lookup_no_matching_platform() -> None:
    fake = FakeRegistry()
    manifest_digest, _config = _image(fake)
    _index(fake, manifest_digest, arch="s390x")

    result = _lookup(fake).lookup(_local_image())

    assert result.image_digest is None
    assert result.repo_digest is None
    assert result.annotations["org.opencontainers.image.source"] == "https://github.com/szabis/iventoy"


def test_lookup_pinned_tag_looked_up_by_tag() -> None:
    fake = FakeRegistry()
    manifest_digest, _config = _image(fake)
    index_digest: str = _index(fake, manifest_digest)
    pinned: str = "sha256:" + "9" * 64

    result = _lookup(fake).lookup(_local_image(f"{FAKE_REGISTRY}/szabis/iventoy:latest@{pinned}"))

    assert result.image_digest == index_digest
    assert fake.registry_requests[0].path.endswith("/manifests/latest")


def test_lookup_with_registry_token() -> None:
    fake = FakeRegistry()
    manifest_digest, _config = _image(fake)
    _index(fake, manifest_digest)
    fake.issued["custom"] = "repository:szabis/iventoy:pull"

    result = _lookup(fake).lookup(_local_image(), token="custom")

    assert result.image_digest is not None
    assert fake.token_requests == []


def test_lookup_auth_failure_recorded() -> None:
    fake = FakeRegistry(users={"me": "secret"})
    manifest_digest, _config = _image(fake)
    _index(fake, manifest_digest)

    result = _lookup(fake).lookup(_local_image())

    assert result.error is not None
    assert result.image_digest is None


def test_lookup_uses_credentials() -> None:
    fake = FakeRegistry(users={"me": "secret"})
    manifest_digest, _config = _image(fake)
    _index(fake, manifest_digest)
    uut = ContainerDistributionAPIVersionLookup(
        _throttler(),
        RegistryConfig(),
        credentials=StaticCredentials({FAKE_REGISTRY: Credentials("me", "secret")}),
        transport=fake.transport(),
    )

    assert uut.lookup(_local_image()).version == "1.0.43"


def test_lookup_rate_limited_throttles() -> None:
    fake = FakeRegistry(auth=None, rate_limited=True)
    throttler = _throttler()

    result = _lookup(fake, throttler).lookup(_local_image())

    assert result.throttled
    throttler.throttle.assert_called_once()
    assert throttler.throttle.call_args.kwargs["retry_secs"] == 42


def test_lookup_skipped_while_throttled() -> None:
    fake = FakeRegistry()
    throttler = _throttler()
    throttler.check_throttle.return_value = True

    assert _lookup(fake, throttler).lookup(_local_image()).throttled
    assert fake.requests == []


def test_lookup_config_rate_limited_keeps_digests() -> None:
    fake = FakeRegistry(auth=None)
    manifest_digest, config_digest = _image(fake)
    _index(fake, manifest_digest)
    throttler = _throttler()
    uut = _lookup(fake, throttler)
    original = fake.handle

    def limit_blobs(method: str, url: str, headers: Any, body: bytes = b"") -> Any:
        if "/blobs/" in url:
            return 429, [("Retry-After", "5")], b""
        return original(method, url, headers, body)

    fake.handle = limit_blobs  # type: ignore[method-assign]
    result = uut.lookup(_local_image())

    assert result.throttled
    assert result.repo_digest == config_digest
    assert result.version is None
    assert throttler.throttle.call_args.kwargs["retry_secs"] == 5


def test_lookup_unreachable_registry() -> None:
    uut = ContainerDistributionAPIVersionLookup(_throttler(), RegistryConfig(), credentials=StaticCredentials({}))
    result = uut.lookup(_local_image("127.0.0.1:9/szabis/iventoy:latest"))
    assert result.error is not None
    assert uut.api_stats.fetches == 1


def test_lookup_default_credentials_from_docker_config() -> None:
    uut = ContainerDistributionAPIVersionLookup(_throttler(), RegistryConfig())
    assert isinstance(uut.client.auth.credentials, DockerConfigCredentials)


@pytest.mark.parametrize(
    ("kind", "immutable", "expected"),
    [("token", False, None), ("manifest", False, 3600), ("manifest", True, 7776000), ("blob", True, 7776000)],
)
def test_registry_cache_ttl(kind: str, immutable: bool, expected: int | None) -> None:
    request = HttpRequest("GET", "https://ghcr.io/v2/a/b/manifests/x", kind=kind, immutable=immutable)
    assert registry_cache_ttl(RegistryConfig(), request) == expected


def test_caching_transport_sets_hishel_ttl() -> None:
    uut = CachingRegistryTransport(RegistryConfig())
    kwargs: dict[str, Any] = {"headers": {}, "extensions": {}}
    uut.set_cache_ttl(HttpRequest("GET", "https://ghcr.io/v2/a/b/blobs/x", kind="blob", immutable=True), kwargs)
    assert kwargs == {"headers": {"Cache-Control": "max-age=7776000"}, "extensions": {"hishel_ttl": 7776000}}
    kwargs = {"headers": {}, "extensions": {}}
    uut.set_cache_ttl(HttpRequest("GET", "https://auth/token", kind="token"), kwargs)
    assert kwargs == {"headers": {}, "extensions": {}}


def test_caching_transport_counts_stats() -> None:
    fake = FakeRegistry(auth=None)
    manifest_digest, _config = _image(fake)
    _index(fake, manifest_digest)
    stats = APIStatsCounter()
    uut = CachingRegistryTransport(RegistryConfig(), stats)
    uut.client = httpx.Client(transport=fake.httpx_transport())
    response = uut.send(HttpRequest("GET", f"https://{FAKE_REGISTRY}/v2/szabis/iventoy/manifests/latest", kind="manifest"))
    assert response.is_success
    assert stats.host_stats[FAKE_REGISTRY].fetches == 1


def test_auth_challenge_not_counted_as_error() -> None:
    from updates2mqtt.integrations.docker_enrich import is_auth_challenge
    from updates2mqtt.oci import Headers, HttpResponse

    request = HttpRequest("GET", "https://ghcr.io/v2/a/b/manifests/latest", kind="manifest")
    challenge = HttpResponse(401, Headers({"WWW-Authenticate": 'Bearer realm="https://ghcr.io/token"'}), b"", request)
    assert is_auth_challenge(request, challenge)
    # credentials sent and still refused is a real failure
    assert not is_auth_challenge(request.with_header("Authorization", "Bearer x"), challenge)
    assert not is_auth_challenge(request, HttpResponse(401, Headers(), b"", request))
    assert not is_auth_challenge(request, HttpResponse(200, Headers(), b"", request))


def test_caching_transport_counts_challenges_separately() -> None:
    fake = FakeRegistry()
    manifest_digest, _config = _image(fake)
    _index(fake, manifest_digest)
    stats = APIStatsCounter()
    transport = CachingRegistryTransport(RegistryConfig(), stats)
    transport.client = httpx.Client(transport=fake.httpx_transport())
    uut = ContainerDistributionAPIVersionLookup(
        _throttler(), RegistryConfig(), credentials=StaticCredentials({}), transport=transport
    )
    assert uut.lookup(_local_image()).image_digest is not None
    host_stats = stats.host_stats[FAKE_REGISTRY]
    assert host_stats.challenges == 1
    assert host_stats.failed == {}
    assert "auth challenges: 1" in str(host_stats)


# === HotioPackageEnricher Tests ===


HOTIO_TREE = {
    "tree": [
        {"path": "docs/containers/base.md"},
        {"path": "docs/containers/sonarr.md"},
        {"path": "docs/containers/autoscan.md"},
        {"path": "docs/webhook-avatars/sonarr.png"},
        {"path": "logos/sonarr.svg"},
    ]
}
HOTIO_SONARR_PAGE = """---
title: hotio/sonarr
---

[:octicons-mark-github-16: GitHub](https://github.com/hotio/sonarr){ class="header-links" }
[:octicons-link-16: Upstream Project](https://github.com/sonarr/sonarr){ class="header-links" }
"""


def hotio_enricher() -> HotioPackageEnricher:
    cfg: DockerConfig = docker_config(discover_metadata={"hotio.dev": MetadataSourceConfig(cache_ttl=0)})
    enricher = HotioPackageEnricher(cfg)
    enricher.initialize()
    return enricher


def test_hotio_enricher_disabled() -> None:
    cfg = docker_config()
    cfg.discover_metadata["hotio.dev"].enabled = False
    enricher = HotioPackageEnricher(cfg)
    enricher.initialize()
    assert len(enricher.containers) == 0
    assert enricher.enrich(DockerImageInfo("ghcr.io/hotio/sonarr:release")) is None


def test_hotio_enricher_lists_images(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=HOTIO_SITE_TREE_URL, json=HOTIO_TREE)
    enricher = hotio_enricher()
    assert enricher.containers == {"sonarr", "autoscan"}
    assert enricher.avatars == {"sonarr"}
    assert len(enricher.pkgs) == 0  # pages only fetched when an image is seen


@pytest.mark.parametrize("ref", ["ghcr.io/hotio/sonarr:release", "hotio/sonarr:latest", "docker.io/hotio/sonarr"])
def test_hotio_enricher_enriches(httpx_mock: HTTPXMock, ref: str) -> None:
    httpx_mock.add_response(url=HOTIO_SITE_TREE_URL, json=HOTIO_TREE)
    httpx_mock.add_response(url=HOTIO_PAGE_URL.format(name="sonarr"), text=HOTIO_SONARR_PAGE)
    enricher = hotio_enricher()
    info: PackageUpdateInfo | None = enricher.enrich(DockerImageInfo(ref))
    assert info is not None
    assert info.source_repo_url == "https://github.com/sonarr/sonarr"
    assert info.release_notes_url == "https://github.com/sonarr/sonarr/releases"
    assert info.logo_url == "https://hotio.dev/webhook-avatars/sonarr.png"
    # second lookup reuses the cached package, no further page fetch
    assert enricher.enrich(DockerImageInfo(ref)) is info


def test_hotio_enricher_page_without_upstream(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=HOTIO_SITE_TREE_URL, json=HOTIO_TREE)
    httpx_mock.add_response(url=HOTIO_PAGE_URL.format(name="autoscan"), status_code=404)
    info: PackageUpdateInfo | None = hotio_enricher().enrich(DockerImageInfo("ghcr.io/hotio/autoscan:release"))
    assert info is not None
    assert info.source_repo_url is None
    assert info.release_notes_url is None
    assert info.logo_url is None


@pytest.mark.parametrize("ref", ["ghcr.io/hotio/unknown:release", "ghcr.io/hotio/base:alpine", "ghcr.io/other/sonarr"])
def test_hotio_enricher_ignores_other_images(httpx_mock: HTTPXMock, ref: str) -> None:
    httpx_mock.add_response(url=HOTIO_SITE_TREE_URL, json=HOTIO_TREE)
    assert hotio_enricher().enrich(DockerImageInfo(ref)) is None


def test_hotio_enricher_handles_api_error(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=HOTIO_SITE_TREE_URL, status_code=403)
    enricher = hotio_enricher()
    assert len(enricher.containers) == 0
    assert enricher.enrich(DockerImageInfo("ghcr.io/hotio/sonarr:release")) is None
