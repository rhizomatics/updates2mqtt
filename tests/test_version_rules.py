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


DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64


def test_installed_image_digest_among_latest_repo_digests() -> None:
    installed = DockerImageInfo("foo", image_digest=DIGEST_A)
    latest = DockerImageInfo("foo", image_digest=DIGEST_B, attributes={"RepoDigests": [f"foo@{DIGEST_A}"]})
    assert select_versions(VersionPolicy.AUTO, installed, latest) == ("a" * 12, "a" * 12, "digest-4-FGA")


def test_latest_image_digest_among_installed_repo_digests() -> None:
    installed = DockerImageInfo("foo", image_digest=DIGEST_A, attributes={"RepoDigests": [f"foo@{DIGEST_B}"]})
    latest = DockerImageInfo("foo", image_digest=DIGEST_B)
    assert select_versions(VersionPolicy.AUTO, installed, latest) == ("a" * 12, "a" * 12, "digest-4-FGB")


def test_non_semver_versions_qualified_with_digest() -> None:
    same = DockerImageInfo("foo:latest", version="nightly", image_digest=DIGEST_A)
    assert select_versions(VersionPolicy.AUTO, same, same) == (
        f"nightly:{'a' * 12}",
        f"nightly:{'a' * 12}",
        "version-digest-3-SDM",
    )
    installed = DockerImageInfo("foo:latest", version="nightly-1", image_digest=DIGEST_A)
    latest = DockerImageInfo("foo:latest", version="nightly-2", image_digest=DIGEST_B)
    assert select_versions(VersionPolicy.AUTO, installed, latest) == (
        f"nightly-1:{'a' * 12}",
        f"nightly-2:{'b' * 12}",
        "version-digest-3",
    )


def test_semver_tags() -> None:
    installed = DockerImageInfo("foo:1.2.3", image_digest=DIGEST_A)
    latest = DockerImageInfo("foo:1.2.4", image_digest=DIGEST_B)
    assert select_versions(VersionPolicy.AUTO, installed, latest) == ("1.2.3", "1.2.4", "semver-tag-1")


def test_installed_version_kept_when_latest_has_only_git_digest() -> None:
    latest = DockerImageInfo("foo")
    latest.git_digest = "abc"
    assert select_versions(VersionPolicy.AUTO, DockerImageInfo("foo", version="1.0"), latest) == ("1.0", "1.0", "version-4")


def test_installed_without_digest_evened_out() -> None:
    latest = DockerImageInfo("foo", image_digest=DIGEST_B)
    assert select_versions(VersionPolicy.AUTO, DockerImageInfo("foo"), latest) == ("b" * 12, "b" * 12, "digest-5")


def test_repo_digests_compared_without_image_digests() -> None:
    installed = DockerImageInfo("foo")
    installed.repo_digest = DIGEST_A
    latest = DockerImageInfo("foo")
    latest.repo_digest = DIGEST_B
    assert select_versions(VersionPolicy.AUTO, installed, latest) == ("a" * 12, "b" * 12, "repo-digest-6")


def test_latest_without_digest_keeps_installed() -> None:
    installed = DockerImageInfo("foo", image_digest=DIGEST_A)
    latest = DockerImageInfo("foo", version="2.0")
    assert select_versions(VersionPolicy.AUTO, installed, latest) == ("a" * 12, "a" * 12, "digest-7")


def test_no_versions_determined() -> None:
    latest = DockerImageInfo("foo")
    latest.git_digest = "abc"
    assert select_versions(VersionPolicy.AUTO, DockerImageInfo("foo"), latest) == ("UNKNOWN", "UNKNOWN", "failure-999")


DIGEST_C = "sha256:" + "c" * 64
DIGEST_D = "sha256:" + "d" * 64


def registry_latest(manifest_digest: str, config_digest: str, version: str | None = None) -> DockerImageInfo:
    """As OCI_V2 lookup builds it: image digest from the manifest, repo and config digest from the config"""
    latest = DockerImageInfo("foo:latest", version=version)
    latest.image_digest = manifest_digest
    latest.short_digest = latest.condense_digest(manifest_digest)
    latest.repo_digest = config_digest
    latest.config_digest = config_digest
    return latest


def test_rebuild_of_same_version_compares_config_digests() -> None:
    # local image id is the config digest, RepoDigests hold the manifest digest
    installed = DockerImageInfo(
        "foo:latest", version="master", image_digest=DIGEST_A, attributes={"RepoDigests": [f"foo@{DIGEST_C}"]}
    )
    latest = registry_latest(DIGEST_D, DIGEST_B, version="master")
    assert select_versions(VersionPolicy.AUTO, installed, latest) == (
        f"master:{'a' * 12}",
        f"master:{'b' * 12}",
        "version-digest-3",
    )
    assert select_versions(VersionPolicy.DIGEST, installed, latest) == ("a" * 12, "b" * 12, "digest-0")


def test_unchanged_image_matched_on_config_digest() -> None:
    installed = DockerImageInfo(
        "foo:latest", version="master", image_digest=DIGEST_A, attributes={"RepoDigests": [f"foo@{DIGEST_C}"]}
    )
    latest = registry_latest(DIGEST_C, DIGEST_A, version="master")
    assert select_versions(VersionPolicy.AUTO, installed, latest) == (
        f"master:{'a' * 12}",
        f"master:{'a' * 12}",
        "version-digest-3-SDM",
    )


def test_rebuild_of_casual_version_qualified_with_digest() -> None:
    installed = DockerImageInfo("foo", version="22.04", image_digest=DIGEST_A, created="2024-01-15T10:30:00Z")
    latest = DockerImageInfo("foo", version="22.04", image_digest=DIGEST_B, created="2024-01-20T14:00:00Z")
    assert select_versions(VersionPolicy.AUTO, installed, latest) == (
        f"22.04:{'a' * 12}",
        f"22.04:{'b' * 12}",
        "version-digest-3",
    )


def test_reuse_keeps_version_created_and_config_digest() -> None:
    original = DockerImageInfo("foo:latest", version="master", image_digest=DIGEST_A, created="2024-01-15T10:30:00Z")
    cloned = original.reuse()
    assert cloned.version == "master"
    assert cloned.created == "2024-01-15T10:30:00Z"
    assert cloned.config_digest == DIGEST_A
    assert cloned.platform is None
