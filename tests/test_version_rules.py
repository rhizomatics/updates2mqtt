from updates2mqtt.config import VersionPolicy
from updates2mqtt.helpers import select_version


def test_good_version_and_digest_matching() -> None:
    assert (
        select_version(
            VersionPolicy.AUTO, version="22.04", digest="b5c7fd5f595a", other_version="22.04", other_digest="b5c7fd5f595a"
        )
        == "22.04"
    )
    assert (
        select_version(
            VersionPolicy.VERSION, version="22.04", digest="b5c7fd5f595a", other_version="22.04", other_digest="b5c7fd5f595a"
        )
        == "22.04"
    )
    assert (
        select_version(
            VersionPolicy.DIGEST, version="22.04", digest="b5c7fd5f595a", other_version="22.04", other_digest="b5c7fd5f595a"
        )
        == "b5c7fd5f595a"
    )
    assert (
        select_version(
            VersionPolicy.VERSION_DIGEST,
            version="22.04",
            digest="b5c7fd5f595a",
            other_version="22.04",
            other_digest="b5c7fd5f595a",
        )
        == "22.04:b5c7fd5f595a"
    )


def test_good_version_and_digest_incremented() -> None:
    assert (
        select_version(
            VersionPolicy.AUTO, version="22.04", digest="b5c7fd5f595a", other_version="22.03", other_digest="917fd52395a"
        )
        == "22.04"
    )
    assert (
        select_version(
            VersionPolicy.VERSION, version="22.04", digest="b5c7fd5f595a", other_version="22.03", other_digest="917fd52395a"
        )
        == "22.04"
    )
    assert (
        select_version(
            VersionPolicy.DIGEST, version="22.04", digest="b5c7fd5f595a", other_version="22.03", other_digest="917fd52395a"
        )
        == "b5c7fd5f595a"
    )
    assert (
        select_version(
            VersionPolicy.VERSION_DIGEST,
            version="22.04",
            digest="b5c7fd5f595a",
            other_version="22.03",
            other_digest="917fd52395a",
        )
        == "22.04:b5c7fd5f595a"
    )


def test_no_version_and_digest_matching() -> None:
    assert (
        select_version(VersionPolicy.AUTO, version=None, digest="b5c7fd5f595a", other_version=None, other_digest="b5c7fd5f595a")
        == "b5c7fd5f595a"
    )
    assert (
        select_version(
            VersionPolicy.VERSION, version=None, digest="b5c7fd5f595a", other_version=None, other_digest="b5c7fd5f595a"
        )
        == "b5c7fd5f595a"
    )
    assert (
        select_version(
            VersionPolicy.DIGEST, version=None, digest="b5c7fd5f595a", other_version=None, other_digest="b5c7fd5f595a"
        )
        == "b5c7fd5f595a"
    )
    assert (
        select_version(
            VersionPolicy.VERSION_DIGEST, version=None, digest="b5c7fd5f595a", other_version=None, other_digest="b5c7fd5f595a"
        )
        == "b5c7fd5f595a"
    )
