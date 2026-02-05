from updates2mqtt.config import VersionPolicy
from updates2mqtt.integrations.docker import select_versions
from updates2mqtt.integrations.docker_enrich import DockerImageInfo


def test_good_version_and_digest_matching() -> None:
    latest = installed = DockerImageInfo("foo", version="22.04", image_digest="b5c7fd5f595a")
    assert select_versions(VersionPolicy.AUTO, installed, latest) == ("22.04", "22.04", "casualver-1-SDM")
    assert select_versions(VersionPolicy.VERSION, installed, latest) == ("22.04", "22.04", "version-0-SDM")
    assert select_versions(VersionPolicy.DIGEST, installed, latest) == ("b5c7fd5f595a", "b5c7fd5f595a", "digest-0-SDM")
    assert select_versions(VersionPolicy.VERSION_DIGEST, installed, latest) == (
        "22.04:b5c7fd5f595a",
        "22.04:b5c7fd5f595a",
        "version-digest-0-SDM",
    )


def test_semver_matching() -> None:
    latest = installed = DockerImageInfo("foo", version="22.4.3", image_digest="b5c7fd5f595a")
    assert select_versions(VersionPolicy.AUTO, installed, latest) == ("22.4.3", "22.4.3", "semver-1-SDM")


def test_good_version_and_digest_incremented() -> None:
    installed = DockerImageInfo("foo", version="22.03", image_digest="917fd52395a")
    latest = DockerImageInfo("foo", version="22.04", image_digest="b5c7fd5f595a")
    assert select_versions(VersionPolicy.AUTO, installed, latest) == ("22.03", "22.04", "casualver-1")
    assert select_versions(VersionPolicy.VERSION, installed, latest) == ("22.03", "22.04", "version-0")
    assert select_versions(VersionPolicy.DIGEST, installed, latest) == ("917fd52395a", "b5c7fd5f595a", "digest-0")
    assert select_versions(VersionPolicy.VERSION_DIGEST, installed, latest) == (
        "22.03:917fd52395a",
        "22.04:b5c7fd5f595a",
        "version-digest-0",
    )


def test_no_version_and_digest_matching() -> None:
    installed = DockerImageInfo("foo", image_digest="b5c7fd5f595a")
    latest = DockerImageInfo("foo", image_digest="b5c7fd5f595a")
    assert select_versions(VersionPolicy.AUTO, installed, latest) == ("b5c7fd5f595a", "b5c7fd5f595a", "digest-4-SDM")
    assert select_versions(VersionPolicy.VERSION, installed, latest) == ("b5c7fd5f595a", "b5c7fd5f595a", "digest-4-SDM")
    assert select_versions(VersionPolicy.DIGEST, installed, latest) == ("b5c7fd5f595a", "b5c7fd5f595a", "digest-0-SDM")
    assert select_versions(VersionPolicy.VERSION_DIGEST, installed, latest) == ("b5c7fd5f595a", "b5c7fd5f595a", "digest-4-SDM")


def test_git_local_versions() -> None:
    installed = DockerImageInfo("foo", image_digest="b5c7fd5f595a")
    installed.git_digest = "9484341a"
    latest = DockerImageInfo("foo")
    latest.git_digest = "9484341a"

    for policy in (VersionPolicy.AUTO, VersionPolicy.DIGEST, VersionPolicy.VERSION, VersionPolicy.VERSION_DIGEST):
        assert select_versions(policy, installed, latest) == ("git:9484341a", "git:9484341a", "git-2")


def test_repo_digests() -> None:
    installed = DockerImageInfo(
        "foo",
        image_digest="b5c7fd5f595a",
        attributes={
            "RepoDigests": [
                "ghcr.io/immich-app/immich-server@sha256:2c496e3b9d476ea723e6f0df05d1f690fed2d79b61f4ed75597679892d86311a",
                "ghcr.io/immich-app/immich-server@sha256:e6a6298e67ae077808fdb7d8d5565955f60b0708191576143fc02d30ab1389d1",
            ]
        },
    )
    latest = DockerImageInfo("foo")
    latest.repo_digest = "sha256:e6a6298e67ae077808fdb7d8d5565955f60b0708191576143fc02d30ab1389d1"

    for policy in (VersionPolicy.AUTO, VersionPolicy.DIGEST, VersionPolicy.VERSION, VersionPolicy.VERSION_DIGEST):
        assert select_versions(policy, installed, latest) == ("e6a6298e67ae", "e6a6298e67ae", "repo-digest-7")


def test_pinned_digests() -> None:
    installed = DockerImageInfo(
        "ghcr.io/immich-app/immich-server:vanity_tag@sha256:2c496e3b9d476ea723e6f0df05d1f690fed2d79b61f4ed75597679892d86311a",
        image_digest="b5c7fd5f595a",
        attributes={
            "RepoDigests": [
                "ghcr.io/immich-app/immich-server@sha256:2c496e3b9d476ea723e6f0df05d1f690fed2d79b61f4ed75597679892d86311a",
                "ghcr.io/immich-app/immich-server@sha256:e6a6298e67ae077808fdb7d8d5565955f60b0708191576143fc02d30ab1389d1",
            ]
        },
    )
    latest = DockerImageInfo("foo")
    latest.repo_digest = "sha256:e6a6298e67ae077808fdb7d8d5565955f60b0708191576143fc02d30ab1389d1"

    for policy in (VersionPolicy.AUTO, VersionPolicy.DIGEST, VersionPolicy.VERSION, VersionPolicy.VERSION_DIGEST):
        assert select_versions(policy, installed, latest) == ("e6a6298e67ae", "e6a6298e67ae", "repo-digest-7")


def test_timestamp_matching_no_update() -> None:
    """TIMESTAMP policy with same timestamp and same digest - no update available."""
    installed = DockerImageInfo("foo", image_digest="b5c7fd5f595a", created="2024-01-15T10:30:00Z")
    latest = DockerImageInfo("foo", image_digest="b5c7fd5f595a", created="2024-01-15T10:30:00Z")
    assert select_versions(VersionPolicy.TIMESTAMP, installed, latest) == (
        "2024-01-15T10:30:00Z",
        "2024-01-15T10:30:00Z",
        "timestamp-0-SDM",
    )


def test_timestamp_update_available() -> None:
    """TIMESTAMP policy with newer timestamp and different digest - update available."""
    installed = DockerImageInfo("foo", image_digest="917fd52395a", created="2024-01-15T10:30:00Z")
    latest = DockerImageInfo("foo", image_digest="b5c7fd5f595a", created="2024-01-20T14:00:00Z")
    assert select_versions(VersionPolicy.TIMESTAMP, installed, latest) == (
        "2024-01-15T10:30:00Z",
        "2024-01-20T14:00:00Z",
        "timestamp-0",
    )


def test_timestamp_same_timestamp_different_digest_fallback() -> None:
    """TIMESTAMP policy with same timestamp but different digest - inconsistent, falls back."""
    installed = DockerImageInfo("foo", image_digest="917fd52395a", created="2024-01-15T10:30:00Z")
    latest = DockerImageInfo("foo", image_digest="b5c7fd5f595a", created="2024-01-15T10:30:00Z")
    # Inconsistent state: same timestamp but different digest, should fall back to version-digest
    result = select_versions(VersionPolicy.TIMESTAMP, installed, latest)
    assert result == ("917fd52395a", "b5c7fd5f595a", "digest-4")


def test_timestamp_different_timestamp_same_digest_fallback() -> None:
    """TIMESTAMP policy with different timestamp but same digest - inconsistent, falls back."""
    installed = DockerImageInfo("foo", image_digest="b5c7fd5f595a", created="2024-01-15T10:30:00Z")
    latest = DockerImageInfo("foo", image_digest="b5c7fd5f595a", created="2024-01-20T14:00:00Z")
    # SDM shortcircuit triggers since digests match
    result = select_versions(VersionPolicy.TIMESTAMP, installed, latest)
    assert result == ("2024-01-15T10:30:00Z", "2024-01-15T10:30:00Z", "timestamp-0-SDM")


def test_timestamp_missing_installed_timestamp_fallback() -> None:
    """TIMESTAMP policy with missing installed timestamp - falls back."""
    installed = DockerImageInfo("foo", image_digest="917fd52395a")
    latest = DockerImageInfo("foo", image_digest="b5c7fd5f595a", created="2024-01-20T14:00:00Z")
    result = select_versions(VersionPolicy.TIMESTAMP, installed, latest)
    # Should fall back to digest-based version
    assert result == ("917fd52395a", "b5c7fd5f595a", "digest-4")


def test_timestamp_missing_latest_timestamp_fallback() -> None:
    """TIMESTAMP policy with missing latest timestamp - falls back."""
    installed = DockerImageInfo("foo", image_digest="917fd52395a", created="2024-01-15T10:30:00Z")
    latest = DockerImageInfo("foo", image_digest="b5c7fd5f595a")
    result = select_versions(VersionPolicy.TIMESTAMP, installed, latest)
    # Should fall back to digest-based version
    assert result == ("917fd52395a", "b5c7fd5f595a", "digest-4")


def test_timestamp_fallback_phase4() -> None:
    """Timestamp used as fallback (phase 4) when no version available."""
    installed = DockerImageInfo("foo", image_digest="917fd52395a", created="2024-01-15T10:30:00Z")
    latest = DockerImageInfo("foo", image_digest="b5c7fd5f595a", created="2024-01-20T14:00:00Z")
    # AUTO policy with no version info should fall back to timestamp at phase 4
    assert select_versions(VersionPolicy.AUTO, installed, latest) == (
        "2024-01-15T10:30:00Z",
        "2024-01-20T14:00:00Z",
        "timestamp-4",
    )


def test_timestamp_with_version_prefers_version() -> None:
    """When both version and timestamp available, version policies should prefer version."""
    installed = DockerImageInfo("foo", version="1.0.0", image_digest="917fd52395a", created="2024-01-15T10:30:00Z")
    latest = DockerImageInfo("foo", version="1.1.0", image_digest="b5c7fd5f595a", created="2024-01-20T14:00:00Z")
    # VERSION policy should use version, not timestamp
    assert select_versions(VersionPolicy.VERSION, installed, latest) == ("1.0.0", "1.1.0", "version-0")
    # AUTO policy should use semver when available
    assert select_versions(VersionPolicy.AUTO, installed, latest) == ("1.0.0", "1.1.0", "semver-1")
    # TIMESTAMP policy should still use timestamp
    assert select_versions(VersionPolicy.TIMESTAMP, installed, latest) == (
        "2024-01-15T10:30:00Z",
        "2024-01-20T14:00:00Z",
        "timestamp-0",
    )


def test_semver_tag() -> None:
    installed = DockerImageInfo("foo/foo:5.3.0", image_digest="b5c7fd5f595a", created="2024-01-15T10:30:00Z")
    latest = DockerImageInfo("foo/foo:5.3.0", image_digest="b5c7fd5f595a", created="2024-01-15T10:30:00Z")
    assert select_versions(VersionPolicy.AUTO, installed, latest) == (
        "5.3.0",
        "5.3.0",
        "semver-tag-1-SDM",
    )
