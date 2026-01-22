from updates2mqtt.config import VersionPolicy
from updates2mqtt.integrations.docker import select_versions
from updates2mqtt.integrations.docker_enrich import DockerImageInfo


def test_good_version_and_digest_matching() -> None:
    latest = installed = DockerImageInfo("foo", version="22.04", image_digest="b5c7fd5f595a")
    assert select_versions(VersionPolicy.AUTO, installed, latest) == ("22.04", "22.04", "causualver-1-M")
    assert select_versions(VersionPolicy.VERSION, installed, latest) == ("22.04", "22.04", "version-0-M")
    assert select_versions(VersionPolicy.DIGEST, installed, latest) == ("b5c7fd5f595a", "b5c7fd5f595a", "digest-0-M")
    assert select_versions(VersionPolicy.VERSION_DIGEST, installed, latest) == (
        "22.04:b5c7fd5f595a",
        "22.04:b5c7fd5f595a",
        "version-digest-0-M",
    )


def test_semver_matching() -> None:
    latest = installed = DockerImageInfo("foo", version="22.4.3", image_digest="b5c7fd5f595a")
    assert select_versions(VersionPolicy.AUTO, installed, latest) == ("22.4.3", "22.4.3", "semver-1-M")


def test_good_version_and_digest_incremented() -> None:
    installed = DockerImageInfo("foo", version="22.03", image_digest="917fd52395a")
    latest = DockerImageInfo("foo", version="22.04", image_digest="b5c7fd5f595a")
    assert select_versions(VersionPolicy.AUTO, installed, latest) == ("22.03", "22.04", "causualver-1")
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
    assert select_versions(VersionPolicy.AUTO, installed, latest) == ("b5c7fd5f595a", "b5c7fd5f595a", "digest-4-M")
    assert select_versions(VersionPolicy.VERSION, installed, latest) == ("b5c7fd5f595a", "b5c7fd5f595a", "digest-4-M")
    assert select_versions(VersionPolicy.DIGEST, installed, latest) == ("b5c7fd5f595a", "b5c7fd5f595a", "digest-0-M")
    assert select_versions(VersionPolicy.VERSION_DIGEST, installed, latest) == ("b5c7fd5f595a", "b5c7fd5f595a", "digest-4-M")


def test_git_local_versions() -> None:
    installed = DockerImageInfo("foo", image_digest="b5c7fd5f595a")
    installed.git_digest = "9484341a"
    latest = DockerImageInfo("foo")
    latest.git_digest = "9484341a"

    for policy in (VersionPolicy.AUTO, VersionPolicy.DIGEST, VersionPolicy.VERSION, VersionPolicy.VERSION_DIGEST):
        assert select_versions(policy, installed, latest) == ("git:9484341a", "git:9484341a", "git-3")


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
