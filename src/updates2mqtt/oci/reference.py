"""Image references, following the distribution reference grammar used by Docker

See https://github.com/distribution/reference/blob/main/reference.go
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .errors import InvalidReferenceError

DOCKER_HUB = "docker.io"
DOCKER_HUB_API_HOST = "registry-1.docker.io"
# legacy names, all meaning Docker Hub
DOCKER_HUB_ALIASES: frozenset[str] = frozenset({"docker.io", "index.docker.io", "registry-1.docker.io"})
DEFAULT_TAG = "latest"

COMPONENT_RE = r"[a-z0-9]+(?:(?:\.|_|__|-+)[a-z0-9]+)*"
REPOSITORY_RE = re.compile(rf"^{COMPONENT_RE}(?:/{COMPONENT_RE})*$")
TAG_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._-]{0,127}$")
DIGEST_RE = re.compile(r"^[a-z0-9]+(?:[.+_-][a-z0-9]+)*:[A-Za-z0-9=_-]{32,}$")


def is_digest(value: str | None) -> bool:
    return bool(value and DIGEST_RE.match(value))


@dataclass(frozen=True)
class Reference:
    """A parsed image reference, e.g. `ghcr.io/org/app:1.2@sha256:...`

    registry: normalized host[:port], `docker.io` for Docker Hub
    repository: path within the registry, with `library/` added for Docker Hub official images
    """

    registry: str
    repository: str
    tag: str | None = None
    digest: str | None = None

    def __post_init__(self) -> None:
        if not REPOSITORY_RE.match(self.repository):
            raise InvalidReferenceError(f"Invalid repository name: {self.repository}")
        if self.tag is not None and not TAG_RE.match(self.tag):
            raise InvalidReferenceError(f"Invalid tag: {self.tag}")
        if self.digest is not None and not is_digest(self.digest):
            raise InvalidReferenceError(f"Invalid digest: {self.digest}")

    @classmethod
    def parse(cls, ref: str) -> Reference:
        if not ref or ref != ref.strip():
            raise InvalidReferenceError(f"Invalid reference: {ref!r}")
        remainder: str = ref
        digest: str | None = None
        if "@" in remainder:
            remainder, digest = remainder.split("@", 1)

        registry: str = DOCKER_HUB
        first, sep, rest = remainder.partition("/")
        # a first component is a registry if it looks like a host, as Docker decides it
        if sep and ("." in first or ":" in first or first == "localhost" or first != first.lower()):
            registry = first
            remainder = rest

        tag: str | None = None
        # a colon after the last slash is a tag, earlier ones belong to the registry port
        last_slash: int = remainder.rfind("/")
        colon: int = remainder.rfind(":")
        if colon > last_slash:
            remainder, tag = remainder[:colon], remainder[colon + 1 :]

        registry = normalize_registry(registry)
        if registry == DOCKER_HUB and "/" not in remainder:
            remainder = f"library/{remainder}"
        return cls(registry=registry, repository=remainder, tag=tag, digest=digest)

    @property
    def api_host(self) -> str:
        """Host serving the distribution API, which differs from the registry name for Docker Hub"""
        return DOCKER_HUB_API_HOST if self.registry == DOCKER_HUB else self.registry

    @property
    def identifier(self) -> str:
        """What to fetch the manifest by, digest taking precedence over tag"""
        return self.digest or self.tag or DEFAULT_TAG

    def with_digest(self, digest: str) -> Reference:
        return Reference(self.registry, self.repository, self.tag, digest)

    def __str__(self) -> str:
        result: str = f"{self.registry}/{self.repository}"
        if self.tag:
            result += f":{self.tag}"
        if self.digest:
            result += f"@{self.digest}"
        return result


def normalize_registry(registry: str) -> str:
    registry = registry.lower()
    return DOCKER_HUB if registry in DOCKER_HUB_ALIASES else registry
