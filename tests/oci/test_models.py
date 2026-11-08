"""Parsing and accessors of registry documents"""

import json
from typing import Any

import pytest

from updates2mqtt.oci import (
    Descriptor,
    Headers,
    HttpRequest,
    HttpResponse,
    Manifest,
    OCIError,
    Platform,
    Reference,
    ResolvedImage,
)
from updates2mqtt.oci.models import compute_digest, verify_digest

DIGEST = "sha256:" + "a" * 64


def response(content: bytes, headers: dict[str, str] | None = None) -> HttpResponse:
    return HttpResponse(
        status_code=200,
        headers=Headers(headers or {}),
        content=content,
        request=HttpRequest("GET", "https://registry.test/v2/org/app/manifests/latest"),
    )


@pytest.mark.parametrize("value", ["linux", "linux/amd64/v1/extra", "linux//v7", ""])
def test_platform_parse_rejects_invalid(value: str) -> None:
    with pytest.raises(ValueError, match="Invalid platform"):
        Platform.parse(value)


def test_platform_arm64_v8_variant_is_implicit() -> None:
    declared = Platform.parse("linux/arm64/v8")
    assert declared.normalized_variant is None
    assert declared.matches(Platform.parse("linux/arm64"))
    assert str(declared) == "linux/arm64/v8"
    assert str(Platform.parse("linux/amd64")) == "linux/amd64"
    assert not Platform.parse("linux/arm/v6").matches(Platform.parse("linux/arm/v7"))


@pytest.mark.parametrize("data", [None, "sha256:abc", {"mediaType": "x"}])
def test_descriptor_rejects_invalid(data: Any) -> None:
    with pytest.raises(OCIError, match="Invalid descriptor"):
        Descriptor.from_dict(data)


def test_compute_digest_unsupported_algorithm() -> None:
    with pytest.raises(OCIError, match="Unsupported digest algorithm"):
        compute_digest(b"x", "nosuchhash")


def test_verify_digest_trusts_unknown_algorithm() -> None:
    verify_digest(b"anything", "future512:" + "0" * 64)


def test_manifest_rejects_non_json() -> None:
    with pytest.raises(OCIError, match="isn't JSON"):
        Manifest.from_response(response(b"<html>"))


def test_manifest_rejects_non_object() -> None:
    with pytest.raises(OCIError, match="isn't a JSON object"):
        Manifest.from_response(response(b"[1, 2]"))


def test_manifest_accessors() -> None:
    content: dict[str, Any] = {
        "schemaVersion": 2,
        "config": {"mediaType": "application/vnd.oci.image.config.v1+json", "digest": DIGEST, "size": 10},
        "layers": [{"mediaType": "application/vnd.oci.image.layer.v1.tar+gzip", "digest": DIGEST, "size": 99}],
        "subject": {"mediaType": "application/vnd.oci.image.manifest.v1+json", "digest": DIGEST},
        "annotations": {"org.opencontainers.image.version": "1.2"},
    }
    raw: bytes = json.dumps(content).encode()
    manifest = Manifest.from_response(
        response(raw, {"content-type": "application/vnd.oci.image.manifest.v1+json; charset=utf-8"})
    )
    assert manifest.media_type == "application/vnd.oci.image.manifest.v1+json"
    assert manifest.digest == compute_digest(raw)
    assert not manifest.is_index
    assert manifest.manifests == []
    assert [layer.size for layer in manifest.layers] == [99]
    assert manifest.subject is not None
    assert manifest.subject.digest == DIGEST
    assert manifest.annotations == {"org.opencontainers.image.version": "1.2"}
    assert manifest.config is not None

    bare = Manifest.from_response(response(b'{"schemaVersion": 2}', {"docker-content-digest": DIGEST}))
    assert bare.digest == DIGEST
    assert bare.media_type is None
    assert bare.subject is None
    assert bare.layers == []
    assert bare.annotations == {}


def test_resolved_image_without_config() -> None:
    image = ResolvedImage(reference=Reference.parse("org/app:latest"), digest=DIGEST, index=None, manifest=None)
    assert image.top is None
    assert image.config_digest is None
    assert image.platform is None
    assert image.labels == {}
    assert image.created is None


def test_resolved_image_docker_config_layout() -> None:
    image = ResolvedImage(
        reference=Reference.parse("org/app:latest"),
        digest=DIGEST,
        index=None,
        manifest=None,
        config={"os": "linux", "architecture": "amd64", "Config": {"Labels": {"a": "b"}, "Created": "2024-01-01"}},
    )
    assert image.platform == Platform("linux", "amd64")
    assert image.labels == {"a": "b"}
    assert image.created == "2024-01-01"
