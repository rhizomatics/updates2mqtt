"""Manifests, descriptors and the other documents fetched from a registry"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .errors import DigestMismatchError, OCIError
from .media_types import INDEX_MEDIA_TYPES

if TYPE_CHECKING:
    from .http import HttpResponse
    from .reference import Reference

HEADER_CONTENT_DIGEST = "docker-content-digest"
# annotation docker buildx puts on attestation manifests in an index
DOCKER_REFERENCE_TYPE = "vnd.docker.reference.type"


@dataclass(frozen=True)
class Platform:
    os: str
    architecture: str
    variant: str | None = None

    @classmethod
    def parse(cls, value: str) -> Platform:
        """From `os/arch[/variant]`, e.g. `linux/arm/v7`"""
        parts: list[str] = value.split("/")
        if len(parts) not in (2, 3) or not all(parts):
            raise ValueError(f"Invalid platform: {value}, expected os/arch[/variant]")
        return cls(parts[0], parts[1], parts[2] if len(parts) == 3 else None)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> Platform | None:
        if not data or not data.get("os") or not data.get("architecture"):
            return None
        return cls(data["os"], data["architecture"], data.get("variant") or None)

    @property
    def normalized_variant(self) -> str | None:
        # arm64 images rarely declare their only variant
        if self.architecture == "arm64" and self.variant == "v8":
            return None
        return self.variant

    def matches(self, other: Platform) -> bool:
        """Same os and architecture, and variant where both declare one"""
        if self.os != other.os or self.architecture != other.architecture:
            return False
        mine, theirs = self.normalized_variant, other.normalized_variant
        return mine is None or theirs is None or mine == theirs

    def __str__(self) -> str:
        return "/".join(p for p in (self.os, self.architecture, self.variant) if p)


@dataclass(frozen=True)
class Descriptor:
    """Pointer to content in a registry, as listed in an index, manifest or referrers response"""

    media_type: str | None
    digest: str
    size: int | None = None
    platform: Platform | None = None
    annotations: dict[str, str] = field(default_factory=dict)
    artifact_type: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Descriptor:
        if not isinstance(data, dict) or not data.get("digest"):
            raise OCIError(f"Invalid descriptor: {data}")
        return cls(
            media_type=data.get("mediaType"),
            digest=data["digest"],
            size=data.get("size"),
            platform=Platform.from_dict(data.get("platform")),
            annotations=data.get("annotations") or {},
            artifact_type=data.get("artifactType"),
        )

    @property
    def is_attestation(self) -> bool:
        return self.annotations.get(DOCKER_REFERENCE_TYPE) == "attestation-manifest" or (
            self.platform is not None and self.platform.os == "unknown"
        )


def compute_digest(content: bytes, algorithm: str = "sha256") -> str:
    try:
        return f"{algorithm}:{hashlib.new(algorithm, content).hexdigest()}"
    except ValueError as e:
        raise OCIError(f"Unsupported digest algorithm {algorithm}") from e


def verify_digest(content: bytes, expected: str) -> None:
    algorithm: str = expected.split(":", 1)[0]
    if algorithm not in hashlib.algorithms_available:
        # can't check, e.g. a future algorithm, so trust the registry
        return
    actual: str = compute_digest(content, algorithm)
    if actual != expected:
        raise DigestMismatchError(f"Content digest {actual} doesn't match {expected}")


@dataclass
class Blob:
    digest: str
    content: bytes
    media_type: str | None = None
    response: HttpResponse | None = field(default=None, repr=False)

    def json(self) -> Any:
        return json.loads(self.content)


@dataclass
class Manifest:
    """Image manifest or index, as served"""

    media_type: str | None
    digest: str
    content: dict[str, Any]
    raw: bytes = field(repr=False)
    response: HttpResponse | None = field(default=None, repr=False)

    @classmethod
    def from_response(cls, response: HttpResponse, expected_digest: str | None = None) -> Manifest:
        raw: bytes = response.content
        if expected_digest:
            verify_digest(raw, expected_digest)
        try:
            content: Any = json.loads(raw)
        except ValueError as e:
            raise OCIError(f"Manifest at {response.request.url} isn't JSON") from e
        if not isinstance(content, dict):
            raise OCIError(f"Manifest at {response.request.url} isn't a JSON object")
        digest: str = expected_digest or response.headers.get(HEADER_CONTENT_DIGEST) or compute_digest(raw)
        media_type: str | None = content.get("mediaType") or response.headers.get("content-type", "").split(";")[0] or None
        return cls(media_type=media_type, digest=digest, content=content, raw=raw, response=response)

    @property
    def is_index(self) -> bool:
        return self.media_type in INDEX_MEDIA_TYPES or ("manifests" in self.content and "config" not in self.content)

    @property
    def manifests(self) -> list[Descriptor]:
        """Entries of an index, empty for an image manifest"""
        return [Descriptor.from_dict(m) for m in self.content.get("manifests") or []]

    @property
    def config(self) -> Descriptor | None:
        config: Any = self.content.get("config")
        return Descriptor.from_dict(config) if isinstance(config, dict) and config.get("digest") else None

    @property
    def layers(self) -> list[Descriptor]:
        return [Descriptor.from_dict(m) for m in self.content.get("layers") or []]

    @property
    def annotations(self) -> dict[str, str]:
        return self.content.get("annotations") or {}

    @property
    def subject(self) -> Descriptor | None:
        subject: Any = self.content.get("subject")
        return Descriptor.from_dict(subject) if isinstance(subject, dict) else None

    def select(self, platform: Platform) -> Descriptor | None:
        """Best index entry for a platform, preferring an exact variant match"""
        candidates: list[Descriptor] = [
            d for d in self.manifests if d.platform is not None and not d.is_attestation and d.platform.matches(platform)
        ]
        for candidate in candidates:
            if candidate.platform is not None and candidate.platform.normalized_variant == platform.normalized_variant:
                return candidate
        return candidates[0] if candidates else None


@dataclass
class ResolvedImage:
    """An image reference resolved to the manifest, and optionally config, for one platform

    digest: of what the reference points to, the index for a multi-platform image
    manifest: the platform's image manifest, None if an index has no entry for the platform
    """

    reference: Reference
    digest: str
    index: Manifest | None
    manifest: Manifest | None
    config: dict[str, Any] | None = None
    config_blob: Blob | None = field(default=None, repr=False)

    @property
    def top(self) -> Manifest | None:
        """What the reference pointed to, index or manifest"""
        return self.index or self.manifest

    @property
    def config_digest(self) -> str | None:
        descriptor: Descriptor | None = self.manifest.config if self.manifest else None
        return descriptor.digest if descriptor else None

    @property
    def platform(self) -> Platform | None:
        if not self.config:
            return None
        return Platform.from_dict(self.config)

    @property
    def labels(self) -> dict[str, str]:
        """Image config labels, OCI configs nest them, as do older Docker ones"""
        if not self.config:
            return {}
        inner: Any = self.config.get("config") or self.config.get("Config") or {}
        return (inner.get("Labels") if isinstance(inner, dict) else None) or {}

    @property
    def created(self) -> str | None:
        if not self.config:
            return None
        inner: Any = self.config.get("config") or self.config.get("Config") or {}
        return self.config.get("created") or (inner.get("created") or inner.get("Created") if isinstance(inner, dict) else None)
