from updates2mqtt.config import VersionPolicy
from updates2mqtt.integrations.docker import select_versions
from updates2mqtt.integrations.docker_enrich import DockerImageInfo


def test_good_version_and_digest_matching() -> None:
    latest = installed = DockerImageInfo("foo", version="22.04", image_digest="b5c7fd5f595a")
    assert select_versions(VersionPolicy.AUTO, installed, latest) == ("22.04", "22.04")
    assert select_versions(VersionPolicy.VERSION, installed, latest) == ("22.04", "22.04")
    assert select_versions(VersionPolicy.DIGEST, installed, latest) == ("b5c7fd5f595a", "b5c7fd5f595a")
    assert select_versions(VersionPolicy.VERSION_DIGEST, installed, latest) == ("22.04:b5c7fd5f595a", "22.04:b5c7fd5f595a")


def test_good_version_and_digest_incremented() -> None:
    installed = DockerImageInfo("foo", version="22.03", image_digest="917fd52395a")
    latest = DockerImageInfo("foo", version="22.04", image_digest="b5c7fd5f595a")
    assert select_versions(VersionPolicy.AUTO, installed, latest) == ("22.03", "22.04")
    assert select_versions(VersionPolicy.VERSION, installed, latest) == ("22.03", "22.04")
    assert select_versions(VersionPolicy.DIGEST, installed, latest) == ("917fd52395a", "b5c7fd5f595a")
    assert select_versions(VersionPolicy.VERSION_DIGEST, installed, latest) == ("22.03:917fd52395a", "22.04:b5c7fd5f595a")


def test_no_version_and_digest_matching() -> None:
    installed = DockerImageInfo("foo", image_digest="b5c7fd5f595a")
    latest = DockerImageInfo("foo", image_digest="b5c7fd5f595a")
    assert select_versions(VersionPolicy.AUTO, installed, latest) == ("b5c7fd5f595a", "b5c7fd5f595a")
    assert select_versions(VersionPolicy.VERSION, installed, latest) == ("b5c7fd5f595a", "b5c7fd5f595a")
    assert select_versions(VersionPolicy.DIGEST, installed, latest) == ("b5c7fd5f595a", "b5c7fd5f595a")
    assert select_versions(VersionPolicy.VERSION_DIGEST, installed, latest) == ("b5c7fd5f595a", "b5c7fd5f595a")
