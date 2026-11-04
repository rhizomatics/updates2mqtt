import pytest

from updates2mqtt.oci import InvalidReferenceError, Reference

DIGEST = "sha256:" + "a" * 64


@pytest.mark.parametrize(
    ("ref", "registry", "repository", "tag", "digest"),
    [
        ("nginx", "docker.io", "library/nginx", None, None),
        ("nginx:1.27", "docker.io", "library/nginx", "1.27", None),
        ("jellyfin/jellyfin", "docker.io", "jellyfin/jellyfin", None, None),
        ("docker.io/jellyfin/jellyfin:10", "docker.io", "jellyfin/jellyfin", "10", None),
        ("index.docker.io/library/nginx", "docker.io", "library/nginx", None, None),
        ("ghcr.io/org/app:1.2.3", "ghcr.io", "org/app", "1.2.3", None),
        ("registry.gitlab.com/group/sub/app", "registry.gitlab.com", "group/sub/app", None, None),
        ("localhost/app", "localhost", "app", None, None),
        ("localhost:5000/app:dev", "localhost:5000", "app", "dev", None),
        ("Registry.Example/app", "registry.example", "app", None, None),
        (f"quay.io/org/app@{DIGEST}", "quay.io", "org/app", None, DIGEST),
        (f"app:1.0@{DIGEST}", "docker.io", "library/app", "1.0", DIGEST),
        (f"registry.example:8443/a/b:c@{DIGEST}", "registry.example:8443", "a/b", "c", DIGEST),
    ],
)
def test_parse(ref: str, registry: str, repository: str, tag: str | None, digest: str | None) -> None:
    parsed = Reference.parse(ref)
    assert (parsed.registry, parsed.repository, parsed.tag, parsed.digest) == (registry, repository, tag, digest)


@pytest.mark.parametrize("ref", ["", " nginx", "UPPER", "app:bad tag", "app@sha256:short", "ghcr.io/", "a//b"])
def test_parse_invalid(ref: str) -> None:
    with pytest.raises(InvalidReferenceError):
        Reference.parse(ref)


def test_invalid_reference_is_value_error() -> None:
    with pytest.raises(ValueError):
        Reference.parse("UPPER")


def test_identifier_prefers_digest() -> None:
    assert Reference.parse("nginx").identifier == "latest"
    assert Reference.parse("nginx:1").identifier == "1"
    assert Reference.parse(f"nginx:1@{DIGEST}").identifier == DIGEST


def test_api_host() -> None:
    assert Reference.parse("nginx").api_host == "registry-1.docker.io"
    assert Reference.parse("ghcr.io/a/b").api_host == "ghcr.io"


def test_str_round_trip() -> None:
    ref = Reference.parse(f"ghcr.io/org/app:1@{DIGEST}")
    assert str(ref) == f"ghcr.io/org/app:1@{DIGEST}"
    assert Reference.parse(str(ref)) == ref
    assert str(Reference.parse("nginx")) == "docker.io/library/nginx"


def test_with_digest() -> None:
    assert Reference.parse("ghcr.io/a/b:1").with_digest(DIGEST).identifier == DIGEST
