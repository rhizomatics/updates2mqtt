from typing import Any

import pytest

from tests.oci.fake_registry import REGISTRY, FakeRegistry, InProcessTransport, digest_of, to_bytes
from updates2mqtt.oci import (
    AuthenticationError,
    Credentials,
    DigestMismatchError,
    Headers,
    HttpRequest,
    HttpResponse,
    NotFoundError,
    Platform,
    RateLimitedError,
    Reference,
    RegistryAuth,
    RegistryClient,
    StaticCredentials,
)
from updates2mqtt.oci import media_types as mt

REPO = "org/app"
REF = f"{REGISTRY}/{REPO}:latest"


def multi_platform(fake: FakeRegistry, repo: str = REPO, tag: str = "latest") -> dict[str, str]:
    """Index with amd64, arm v6 and v7, and an attestation, returns digests by platform"""
    digests: dict[str, str] = {}
    entries: list[dict[str, Any]] = []
    for platform in ("linux/amd64", "linux/arm/v6", "linux/arm/v7"):
        os_, arch, *variant = platform.split("/")
        manifest_digest, _config = fake.add_image(repo, None, os_, arch, labels={"platform": platform})
        digests[platform] = manifest_digest
        entry: dict[str, Any] = {
            "mediaType": mt.OCI_MANIFEST,
            "digest": manifest_digest,
            "platform": {"os": os_, "architecture": arch},
        }
        if variant:
            entry["platform"]["variant"] = variant[0]
        entries.append(entry)
    entries.append(
        {
            "mediaType": mt.OCI_MANIFEST,
            "digest": digests["linux/amd64"],
            "platform": {"os": "unknown", "architecture": "unknown"},
            "annotations": {"vnd.docker.reference.type": "attestation-manifest"},
        }
    )
    digests["index"] = fake.add_manifest(
        repo,
        {"schemaVersion": 2, "mediaType": mt.OCI_INDEX, "manifests": entries, "annotations": {"source": "index"}},
        tag,
    )
    return digests


def client(fake: FakeRegistry, **kwargs: Any) -> RegistryClient:
    return RegistryClient(fake.transport(), **kwargs)


# === resolve ===


def test_resolve_multi_platform() -> None:
    fake = FakeRegistry()
    digests = multi_platform(fake)
    image = client(fake).resolve(REF, "linux/amd64")
    assert image.digest == digests["index"]
    assert image.index is not None
    assert image.index.annotations == {"source": "index"}
    assert image.manifest is not None
    assert image.manifest.digest == digests["linux/amd64"]
    assert image.labels == {"platform": "linux/amd64"}
    assert image.created == "2026-01-02T03:04:05Z"
    assert image.platform == Platform("linux", "amd64")
    assert image.manifest.config is not None
    assert image.config_digest == image.manifest.config.digest


@pytest.mark.parametrize(
    ("platform", "expected"),
    [("linux/arm/v7", "linux/arm/v7"), ("linux/arm/v6", "linux/arm/v6"), ("linux/arm", "linux/arm/v6")],
)
def test_resolve_selects_variant(platform: str, expected: str) -> None:
    fake = FakeRegistry()
    digests = multi_platform(fake)
    image = client(fake).resolve(REF, platform)
    assert image.manifest is not None
    assert image.manifest.digest == digests[expected]


def test_resolve_platform_missing_or_unspecified() -> None:
    fake = FakeRegistry()
    multi_platform(fake)
    for platform in ("linux/s390x", None):
        image = client(fake).resolve(REF, platform)
        assert image.index is not None
        assert image.manifest is None
        assert image.config is None


def test_resolve_single_platform_without_index() -> None:
    fake = FakeRegistry()
    manifest_digest, config_digest = fake.add_image(REPO, "latest", labels={"v": "1"})
    image = client(fake).resolve(REF, "linux/amd64")
    assert image.index is None
    assert image.digest == manifest_digest
    assert image.config_digest == config_digest
    assert image.labels == {"v": "1"}


def test_resolve_without_config() -> None:
    fake = FakeRegistry()
    multi_platform(fake)
    image = client(fake).resolve(REF, "linux/amd64", fetch_config=False)
    assert image.manifest is not None
    assert image.config is None
    assert not any("/blobs/" in r.path for r in fake.requests)


def test_blob_redirect_followed() -> None:
    fake = FakeRegistry(redirect_blobs=True)
    multi_platform(fake)
    image = client(fake).resolve(REF, "linux/amd64")
    assert image.labels == {"platform": "linux/amd64"}
    assert fake.requests[-1].path.startswith("/cdn/")


def test_digest_computed_without_header() -> None:
    fake = FakeRegistry(content_digest_header=False)
    digests = multi_platform(fake)
    assert client(fake).resolve(REF, "linux/amd64").digest == digests["index"]


def test_tampered_blob_rejected() -> None:
    fake = FakeRegistry()
    _manifest, config_digest = fake.add_image(REPO, "latest")
    fake.blobs[config_digest] = b'{"tampered": true}'
    with pytest.raises(DigestMismatchError):
        client(fake).resolve(REF, "linux/amd64")


def test_get_manifest_by_digest_verified() -> None:
    fake = FakeRegistry()
    manifest_digest, _config = fake.add_image(REPO, "latest")
    manifest = client(fake).get_manifest(f"{REGISTRY}/{REPO}@{manifest_digest}")
    assert manifest.digest == manifest_digest
    fake.manifests[REPO, manifest_digest] = (mt.OCI_MANIFEST, to_bytes({"schemaVersion": 2, "config": {}}))
    with pytest.raises(DigestMismatchError):
        client(fake).get_manifest(f"{REGISTRY}/{REPO}@{manifest_digest}")


def test_head_manifest() -> None:
    fake = FakeRegistry()
    digests = multi_platform(fake)
    assert client(fake).head_manifest(REF) == digests["index"]
    assert fake.registry_requests[-1].method == "HEAD"


def test_not_found() -> None:
    fake = FakeRegistry()
    with pytest.raises(NotFoundError) as exc_info:
        client(fake).get_manifest(REF)
    assert exc_info.value.errors[0]["code"] == "MANIFEST_UNKNOWN"


def test_rate_limited() -> None:
    fake = FakeRegistry(auth=None, rate_limited=True)
    with pytest.raises(RateLimitedError) as exc_info:
        client(fake).get_manifest(REF)
    assert exc_info.value.retry_after == 42


# === auth ===


def test_anonymous_token_then_proactive() -> None:
    fake = FakeRegistry()
    multi_platform(fake)
    multi_platform(fake, repo="org/other")
    uut = client(fake)
    uut.get_manifest(REF)
    # challenged, fetched token, retried
    assert [r.path == "/token" for r in fake.requests] == [False, True, False]
    assert "authorization" not in fake.requests[0].headers
    assert fake.requests[2].headers["authorization"].startswith("Bearer ")
    assert fake.token_requests[0].params == {"scope": f"repository:{REPO}:pull", "service": REGISTRY}

    fake.requests.clear()
    uut.get_manifest(f"{REGISTRY}/org/other:latest")
    # host known to challenge, so token fetched before the first request
    assert [r.path == "/token" for r in fake.requests] == [True, False]


def test_token_cached_until_expiry() -> None:
    fake = FakeRegistry(expires_in=100)
    multi_platform(fake)
    now: list[float] = [1000.0]
    uut = client(fake, auth=RegistryAuth(clock=lambda: now[0]))
    uut.get_manifest(REF)
    uut.get_manifest(REF)
    assert len(fake.token_requests) == 1
    now[0] += 95
    uut.get_manifest(REF)
    assert len(fake.token_requests) == 2


def test_rejected_token_refreshed() -> None:
    fake = FakeRegistry()
    multi_platform(fake)
    uut = client(fake)
    uut.get_manifest(REF)
    fake.issued.clear()  # registry forgets its tokens, e.g. a restart
    uut.get_manifest(REF)
    assert len(fake.token_requests) == 2


def test_token_with_credentials() -> None:
    fake = FakeRegistry(users={"me": "secret"})
    multi_platform(fake)
    uut = client(fake, credentials=StaticCredentials({REGISTRY: Credentials("me", "secret")}))
    assert uut.get_manifest(REF).is_index
    assert fake.token_requests[0].headers["authorization"].startswith("Basic ")


def test_token_without_required_credentials() -> None:
    fake = FakeRegistry(users={"me": "secret"})
    multi_platform(fake)
    with pytest.raises(AuthenticationError):
        client(fake).get_manifest(REF)
    with pytest.raises(AuthenticationError):
        client(fake, credentials=StaticCredentials({REGISTRY: Credentials("me", "wrong")})).get_manifest(REF)


def test_identity_token() -> None:
    fake = FakeRegistry(identity_tokens={"refresh-me"})
    multi_platform(fake)
    uut = client(fake, credentials=StaticCredentials({REGISTRY: Credentials(identity_token="refresh-me")}))
    assert uut.get_manifest(REF).is_index
    assert fake.token_requests[0].method == "POST"


def test_registry_token_credentials() -> None:
    fake = FakeRegistry()
    multi_platform(fake)
    fake.issued["static"] = f"repository:{REPO}:pull"
    uut = client(fake, credentials=StaticCredentials({REGISTRY: Credentials(registry_token="static")}))
    assert uut.get_manifest(REF).is_index
    assert fake.token_requests == []


def test_basic_auth_registry() -> None:
    fake = FakeRegistry(auth="basic", users={"me": "secret"})
    multi_platform(fake)
    assert client(fake, credentials=StaticCredentials({REGISTRY: Credentials("me", "secret")})).get_manifest(REF)
    with pytest.raises(AuthenticationError):
        client(fake).get_manifest(REF)


def test_explicit_token() -> None:
    fake = FakeRegistry()
    multi_platform(fake)
    fake.issued["given"] = f"repository:{REPO}:pull"
    client(fake).get_manifest(REF, token="given")
    assert fake.token_requests == []


def test_explicit_token_rejected_falls_back_to_challenge() -> None:
    fake = FakeRegistry()
    multi_platform(fake)
    fake.issued["other"] = "repository:org/other:pull"
    assert client(fake).get_manifest(REF, token="other").is_index
    assert len(fake.token_requests) == 1


def test_anonymous_registry() -> None:
    fake = FakeRegistry(auth=None)
    multi_platform(fake)
    client(fake).get_manifest(REF)
    assert fake.token_requests == []


# === tags and referrers ===


def test_list_tags_paginated() -> None:
    fake = FakeRegistry(auth=None, page_size=2)
    fake.tags[REPO] = ["5", "1", "3", "2", "4"]
    assert client(fake).list_tags(REF) == ["1", "2", "3", "4", "5"]
    assert len(fake.registry_requests) == 3
    assert client(fake).list_tags(REF, page_size=10) == ["1", "2", "3", "4", "5"]
    assert client(fake).list_tags(REF, limit=3) == ["1", "2", "3"]


def referrer(artifact_type: str, digest: str) -> dict[str, Any]:
    return {"mediaType": mt.OCI_MANIFEST, "digest": digest, "size": 1, "artifactType": artifact_type}


def test_list_referrers_api() -> None:
    fake = FakeRegistry(auth=None)
    subject = "sha256:" + "1" * 64
    fake.referrers[subject] = [
        referrer("application/vnd.dev.sigstore.bundle", "sha256:" + "2" * 64),
        referrer("application/spdx+json", "sha256:" + "3" * 64),
    ]
    uut = client(fake)
    assert len(uut.list_referrers(REF, subject)) == 2
    sboms = uut.list_referrers(REF, subject, artifact_type="application/spdx+json")
    assert [d.digest for d in sboms] == ["sha256:" + "3" * 64]


def test_list_referrers_tag_fallback() -> None:
    fake = FakeRegistry(auth=None, referrers_api=False)
    subject = "sha256:" + "1" * 64
    uut = client(fake)
    assert uut.list_referrers(REF, subject) == []
    fake.add_manifest(
        REPO,
        {
            "schemaVersion": 2,
            "mediaType": mt.OCI_INDEX,
            "manifests": [referrer("a", "sha256:" + "2" * 64), referrer("b", "sha256:" + "3" * 64)],
        },
        tag=subject.replace(":", "-"),
    )
    assert [d.artifact_type for d in uut.list_referrers(REF, subject, artifact_type="b")] == ["b"]


# === transport details ===


class RecordingTransport:
    def __init__(self) -> None:
        self.sent: list[HttpRequest] = []
        self.closed: bool = False

    def send(self, request: HttpRequest) -> HttpResponse:
        self.sent.append(request)
        return HttpResponse(200, Headers({"content-type": "application/json"}), b'{"tags": []}', request)

    def close(self) -> None:
        self.closed = True


def test_insecure_registries_use_http() -> None:
    transport = RecordingTransport()
    uut = RegistryClient(transport, insecure_registries={"localhost", "insecure.example"})
    for ref in ("localhost:5000/app", "insecure.example/app", "ghcr.io/org/app", "nginx"):
        uut.list_tags(ref)
    assert [r.url for r in transport.sent] == [
        "http://localhost:5000/v2/app/tags/list",
        "http://insecure.example/v2/app/tags/list",
        "https://ghcr.io/v2/org/app/tags/list",
        "https://registry-1.docker.io/v2/library/nginx/tags/list",
    ]


def test_requests_describe_themselves() -> None:
    fake = FakeRegistry()
    multi_platform(fake)
    seen: list[HttpRequest] = []

    class Spy(InProcessTransport):
        def send(self, request: HttpRequest) -> HttpResponse:
            seen.append(request)
            return super().send(request)

    RegistryClient(Spy(fake)).resolve(REF, "linux/amd64")
    assert [(r.kind, r.immutable) for r in seen] == [
        ("manifest", False),
        ("token", False),
        ("manifest", False),
        ("manifest", True),
        ("blob", True),
    ]
    assert {r.registry for r in seen if r.kind != "token"} == {REGISTRY}
    assert {r.scope for r in seen if r.kind != "token"} == {f"repository:{REPO}:pull"}


def test_reference_object_accepted() -> None:
    fake = FakeRegistry(auth=None)
    multi_platform(fake)
    assert client(fake).get_manifest(Reference.parse(REF)).digest == digest_of(fake.manifests[REPO, "latest"][1])


def test_closes_only_own_transport() -> None:
    transport = RecordingTransport()
    with RegistryClient(transport):
        pass
    assert not transport.closed
    with RegistryClient() as uut:
        assert uut.transport is not None
