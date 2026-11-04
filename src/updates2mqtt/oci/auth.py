"""Registry authentication, as an httpx auth flow so the same logic serves sync and async clients

Implements the token flow from https://distribution.github.io/distribution/spec/auth/token/
and the OAuth2 refresh token variant used by `docker login` identity tokens
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import subprocess  # nosec B404
import time
from collections.abc import Callable, Generator, Mapping
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Protocol

from .errors import RateLimitedError
from .http import HttpRequest, HttpResponse, with_query
from .reference import DOCKER_HUB, normalize_registry

log = logging.getLogger(__name__)

# what `docker login` stores Docker Hub credentials under
DOCKER_HUB_CONFIG_KEY = "https://index.docker.io/v1/"
DEFAULT_TOKEN_LIFETIME = 60  # seconds, per the token spec when expires_in absent
CREDENTIAL_HELPER_TIMEOUT = 10
OAUTH_CLIENT_ID = "updates2mqtt-oci"


# RFC 7230 tchar, for auth scheme and parameter names
_TCHARS = r"[!#$%&'*+\-.^_`|~0-9A-Za-z]+"
_SCHEME_RE = re.compile(rf"\s*,?\s*({_TCHARS})(?:\s+|\s*$)")
_PARAM_RE = re.compile(rf'\s*({_TCHARS})\s*=\s*("(?:[^"\\]|\\.)*"|[^,\s]*)\s*(?:,|$)')


@dataclass(frozen=True)
class Challenge:
    scheme: str  # lower case, e.g. bearer or basic
    params: dict[str, str] = field(default_factory=dict)

    @property
    def realm(self) -> str | None:
        return self.params.get("realm")

    @property
    def service(self) -> str | None:
        return self.params.get("service")

    @property
    def scope(self) -> str | None:
        return self.params.get("scope")


def parse_www_authenticate(*headers: str) -> list[Challenge]:
    """Parse challenges, with parameters in any order and quoted values that may contain commas"""
    challenges: list[Challenge] = []
    for header in headers:
        pos: int = 0
        while pos < len(header):
            scheme_match: re.Match[str] | None = _SCHEME_RE.match(header, pos)
            if not scheme_match:
                break
            pos = scheme_match.end()
            params: dict[str, str] = {}
            while pos < len(header):
                param_match: re.Match[str] | None = _PARAM_RE.match(header, pos)
                if not param_match:
                    break
                value: str = param_match.group(2)
                if value.startswith('"'):
                    value = re.sub(r"\\(.)", r"\1", value[1:-1])
                params[param_match.group(1).lower()] = value
                pos = param_match.end()
            challenges.append(Challenge(scheme_match.group(1).lower(), params))
    return challenges


def parse_retry_after(value: str | None) -> float | None:
    """Seconds, from either form of Retry-After"""
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        return max(0.0, parsedate_to_datetime(value).timestamp() - time.time())
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class Credentials:
    username: str | None = None
    password: str | None = None
    # OAuth2 refresh token, as `docker login` stores for some registries, e.g. Azure
    identity_token: str | None = None
    # bearer token to send as is, skipping the token service
    registry_token: str | None = None

    @property
    def has_basic(self) -> bool:
        return bool(self.username and self.password is not None)

    def basic_header(self) -> str:
        encoded: str = base64.b64encode(f"{self.username}:{self.password}".encode()).decode()
        return f"Basic {encoded}"


class CredentialStore(Protocol):
    def get(self, registry: str) -> Credentials | None:
        """Credentials for a registry, as normalized by `Reference`, e.g. `docker.io` or `ghcr.io`"""
        ...


class StaticCredentials:
    """Fixed credentials by registry name"""

    def __init__(self, credentials: Mapping[str, Credentials]) -> None:
        self.credentials: dict[str, Credentials] = {normalize_registry(k): v for k, v in credentials.items()}

    def get(self, registry: str) -> Credentials | None:
        return self.credentials.get(normalize_registry(registry))


class ChainedCredentials:
    """First store with credentials wins"""

    def __init__(self, *stores: CredentialStore) -> None:
        self.stores: tuple[CredentialStore, ...] = stores

    def get(self, registry: str) -> Credentials | None:
        for store in self.stores:
            found: Credentials | None = store.get(registry)
            if found is not None:
                return found
        return None


def config_key_registry(key: str) -> str:
    """Registry name for a docker config key, which may be a URL, e.g. https://index.docker.io/v1/"""
    host: str = re.sub(r"^[a-z]+://", "", key.strip()).split("/", 1)[0]
    return normalize_registry(host)


def run_credential_helper(helper: str, server: str) -> dict[str, Any] | None:
    """Ask a `docker-credential-<helper>` for credentials, None if it has none or isn't installed"""
    try:
        proc = subprocess.run(  # nosec B603
            [f"docker-credential-{helper}", "get"],
            input=server,
            capture_output=True,
            text=True,
            timeout=CREDENTIAL_HELPER_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as e:
        log.debug("Credential helper %s unavailable: %s", helper, e)
        return None
    if proc.returncode != 0:
        log.debug("Credential helper %s has no credentials for %s: %s", helper, server, proc.stdout.strip())
        return None
    try:
        result: Any = json.loads(proc.stdout)
    except ValueError:
        log.warning("Credential helper %s returned invalid JSON", helper)
        return None
    return result if isinstance(result, dict) else None


class DockerConfigCredentials:
    """Credentials as `docker login` saves them, from `$DOCKER_CONFIG/config.json` or `~/.docker/config.json`

    Supports `auths` entries, including identity and registry tokens, `credHelpers` and `credsStore`
    """

    def __init__(
        self,
        path: str | Path | None = None,
        helper_runner: Callable[[str, str], dict[str, Any] | None] = run_credential_helper,
    ) -> None:
        if path is None:
            config_dir: str | None = os.environ.get("DOCKER_CONFIG")
            path = Path(config_dir) / "config.json" if config_dir else Path.home() / ".docker" / "config.json"
        self.path: Path = Path(path)
        self.helper_runner: Callable[[str, str], dict[str, Any] | None] = helper_runner
        self._config: dict[str, Any] = {}
        self._mtime: float | None = None
        self._helper_cache: dict[str, Credentials | None] = {}

    def config(self) -> dict[str, Any]:
        """Reloaded whenever the file changes, e.g. after a new `docker login`"""
        try:
            mtime: float = self.path.stat().st_mtime
        except OSError:
            self._config, self._mtime = {}, None
            return self._config
        if mtime != self._mtime:
            try:
                loaded: Any = json.loads(self.path.read_text())
                self._config = loaded if isinstance(loaded, dict) else {}
            except (OSError, ValueError) as e:
                log.warning("Unable to read docker config %s: %s", self.path, e)
                self._config = {}
            self._mtime = mtime
            self._helper_cache.clear()
        return self._config

    def get(self, registry: str) -> Credentials | None:
        registry = normalize_registry(registry)
        config: dict[str, Any] = self.config()

        helpers: dict[str, str] = {config_key_registry(k): v for k, v in (config.get("credHelpers") or {}).items()}
        helper: str | None = helpers.get(registry) or config.get("credsStore")
        if helper:
            if registry not in self._helper_cache:
                self._helper_cache[registry] = self.from_helper(helper, registry)
            if self._helper_cache[registry] is not None:
                return self._helper_cache[registry]

        for key, entry in (config.get("auths") or {}).items():
            if config_key_registry(key) == registry and isinstance(entry, dict):
                found: Credentials | None = self.from_auths_entry(entry)
                if found is not None:
                    return found
        return None

    def from_helper(self, helper: str, registry: str) -> Credentials | None:
        server: str = DOCKER_HUB_CONFIG_KEY if registry == DOCKER_HUB else registry
        result: dict[str, Any] | None = self.helper_runner(helper, server)
        if not result or not result.get("Secret"):
            return None
        if result.get("Username") == "<token>":
            return Credentials(identity_token=result["Secret"])
        return Credentials(username=result.get("Username"), password=result["Secret"])

    @staticmethod
    def from_auths_entry(entry: dict[str, Any]) -> Credentials | None:
        username: str | None = entry.get("username")
        password: str | None = entry.get("password")
        if entry.get("auth"):
            try:
                username, _, password = base64.b64decode(entry["auth"]).decode().partition(":")
            except ValueError:
                log.warning("Invalid auth entry in docker config")
        if entry.get("identitytoken"):
            return Credentials(username=username, identity_token=entry["identitytoken"])
        if entry.get("registrytoken"):
            return Credentials(registry_token=entry["registrytoken"])
        if username and password is not None:
            return Credentials(username=username, password=password)
        return None


@dataclass
class _Token:
    value: str
    expires_at: float


class RegistryAuth:
    """Answers registry challenges, fetching and caching bearer tokens

    Transport-neutral: `flow` yields the requests to send and receives their responses.
    Once a host has challenged, later requests to it get a token up front, saving a round trip.
    A request already carrying an Authorization header is sent as is, falling back to the
    challenge flow if it's rejected.
    """

    def __init__(self, credentials: CredentialStore | None = None, clock: Callable[[], float] = time.monotonic) -> None:
        self.credentials: CredentialStore | None = credentials
        self.clock: Callable[[], float] = clock
        self.tokens: dict[tuple[str, str | None, str | None], _Token] = {}
        self.challenges: dict[str, Challenge] = {}

    def lookup_credentials(self, registry: str | None) -> Credentials | None:
        if not self.credentials or not registry:
            return None
        try:
            return self.credentials.get(registry)
        except Exception as e:
            log.warning("Credential lookup for %s failed: %s", registry, e)
            return None

    def flow(self, request: HttpRequest) -> Generator[HttpRequest, HttpResponse, HttpResponse]:
        """Send a request, authenticating as needed, returning the final response"""
        host: str = request.host
        preauthorized: bool = request.header("authorization") is not None

        known: Challenge | None = self.challenges.get(host)
        sent: HttpRequest = request
        if known is not None and not preauthorized:
            sent = (yield from self.authorize(request, known, request.scope, refresh=False)) or request

        response: HttpResponse = yield sent
        if response.status_code != 401:
            return response

        challenges: list[Challenge] = parse_www_authenticate(*response.headers.get_list("www-authenticate"))
        challenge: Challenge | None = next((c for c in challenges if c.scheme == "bearer" and c.realm), None) or next(
            (c for c in challenges if c.scheme == "basic"), None
        )
        if challenge is None:
            log.debug("No usable challenge from %s: %s", host, response.headers.get_list("www-authenticate"))
            return response
        self.challenges[host] = Challenge(challenge.scheme, {k: v for k, v in challenge.params.items() if k != "error"})
        # the challenge scope may be wider than ours, e.g. for a cross repository mount
        scope: str | None = challenge.scope or request.scope
        retry: HttpRequest | None = yield from self.authorize(
            request, challenge, scope, refresh=preauthorized or known is not None
        )
        if retry is None:
            return response
        return (yield retry)

    def authorize(
        self, request: HttpRequest, challenge: Challenge, scope: str | None, refresh: bool
    ) -> Generator[HttpRequest, HttpResponse, HttpRequest | None]:
        """Copy of the request with an Authorization header, None if no credentials or token"""
        credentials: Credentials | None = self.lookup_credentials(request.registry)
        if challenge.scheme == "basic":
            if credentials is None or not credentials.has_basic:
                return None
            return request.with_header("Authorization", credentials.basic_header())
        token: str | None = yield from self.token_flow(challenge, scope, credentials, refresh=refresh)
        if token is None:
            return None
        return request.with_header("Authorization", f"Bearer {token}")

    def token_flow(
        self, challenge: Challenge, scope: str | None, credentials: Credentials | None, refresh: bool = False
    ) -> Generator[HttpRequest, HttpResponse, str | None]:
        if credentials is not None and credentials.registry_token:
            return credentials.registry_token
        realm: str | None = challenge.realm
        if not realm:
            return None
        key: tuple[str, str | None, str | None] = (realm, challenge.service, scope)
        cached: _Token | None = self.tokens.get(key)
        if cached is not None and not refresh and cached.expires_at > self.clock():
            return cached.value

        params: dict[str, str] = {k: v for k, v in (("service", challenge.service), ("scope", scope)) if v}
        token_request: HttpRequest
        if credentials is not None and credentials.identity_token:
            token_request = HttpRequest(
                "POST",
                realm,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                form={
                    "grant_type": "refresh_token",
                    "refresh_token": credentials.identity_token,
                    "client_id": OAUTH_CLIENT_ID,
                    **params,
                },
                kind="token",
            )
        else:
            headers: dict[str, str] = {}
            if credentials is not None and credentials.has_basic:
                headers["Authorization"] = credentials.basic_header()
            token_request = HttpRequest("GET", with_query(realm, params), headers=headers, kind="token")

        response: HttpResponse = yield token_request
        if response.status_code == 429:
            raise RateLimitedError(
                f"Token service {realm} rate limited", retry_after=parse_retry_after(response.headers.get("retry-after"))
            )
        if not response.is_success:
            log.warning("Token request to %s for %s failed: %s", realm, scope, response.status_code)
            return None
        try:
            data: Any = response.json()
        except ValueError:
            log.warning("Token response from %s isn't JSON", realm)
            return None
        token: str | None = (data.get("token") or data.get("access_token")) if isinstance(data, dict) else None
        if not token:
            log.warning("No token in response from %s", realm)
            return None
        try:
            lifetime: float = float(data.get("expires_in") or DEFAULT_TOKEN_LIFETIME)
        except (TypeError, ValueError):
            lifetime = DEFAULT_TOKEN_LIFETIME
        # renew a little early, so a token doesn't expire in flight
        self.tokens[key] = _Token(token, self.clock() + lifetime * 0.9)
        return token
