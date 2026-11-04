"""Errors raised by the OCI registry client"""

from __future__ import annotations

from typing import Any


class OCIError(Exception):
    """Base for all OCI client errors"""


class InvalidReferenceError(OCIError, ValueError):
    """Image reference doesn't follow the distribution reference grammar"""


class TransportError(OCIError):
    """Couldn't reach the registry, e.g. connection refused, TLS failure or timeout"""


class RegistryError(OCIError):
    """Registry returned an unsuccessful response"""

    def __init__(self, message: str, status_code: int | None = None, errors: list[dict[str, Any]] | None = None) -> None:
        super().__init__(message)
        self.status_code: int | None = status_code
        # OCI error body entries, each with `code` and `message`
        self.errors: list[dict[str, Any]] = errors or []


class AuthenticationError(RegistryError):
    """Credentials missing or rejected, or no token could be obtained"""


class NotFoundError(RegistryError):
    """Repository, manifest, blob or tag doesn't exist"""


class RateLimitedError(RegistryError):
    """Registry returned 429, retry_after is in seconds if the registry said"""

    def __init__(self, message: str, retry_after: float | None = None, errors: list[dict[str, Any]] | None = None) -> None:
        super().__init__(message, status_code=429, errors=errors)
        self.retry_after: float | None = retry_after


class DigestMismatchError(OCIError):
    """Content didn't hash to the digest it was fetched by"""
