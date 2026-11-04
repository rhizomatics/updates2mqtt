"""Read-only client for OCI distribution registries, e.g. Docker Hub, GHCR, Quay, GitLab

Self-contained, so it can be published separately: the protocol logic is free of I/O, and
runs over niquests or httpx through the adapters in `transports`, or any other `Transport`. Nothing here may import from the rest of updates2mqtt, a test enforces that.

    with RegistryClient(credentials=DockerConfigCredentials()) as client:
        image = client.resolve("ghcr.io/org/app:latest", "linux/amd64")
        print(image.digest, image.labels.get("org.opencontainers.image.version"))
"""

from .auth import (
    ChainedCredentials,
    Challenge,
    Credentials,
    CredentialStore,
    DockerConfigCredentials,
    RegistryAuth,
    StaticCredentials,
    parse_www_authenticate,
)
from .client import (
    DEFAULT_INSECURE_REGISTRIES,
    AsyncRegistryClient,
    RegistryClient,
)
from .errors import (
    AuthenticationError,
    DigestMismatchError,
    InvalidReferenceError,
    NotFoundError,
    OCIError,
    RateLimitedError,
    RegistryError,
    TransportError,
)
from .http import AsyncTransport, Headers, HttpRequest, HttpResponse, Transport
from .models import Blob, Descriptor, Manifest, Platform, ResolvedImage
from .reference import Reference

__all__ = [
    "DEFAULT_INSECURE_REGISTRIES",
    "AsyncRegistryClient",
    "AsyncTransport",
    "AuthenticationError",
    "Blob",
    "ChainedCredentials",
    "Challenge",
    "CredentialStore",
    "Credentials",
    "Descriptor",
    "DigestMismatchError",
    "DockerConfigCredentials",
    "Headers",
    "HttpRequest",
    "HttpResponse",
    "InvalidReferenceError",
    "Manifest",
    "NotFoundError",
    "OCIError",
    "Platform",
    "RateLimitedError",
    "Reference",
    "RegistryAuth",
    "RegistryClient",
    "RegistryError",
    "ResolvedImage",
    "StaticCredentials",
    "Transport",
    "TransportError",
    "parse_www_authenticate",
]
