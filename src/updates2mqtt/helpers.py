import datetime as dt
import re
import time
from threading import Event
from typing import Any

import structlog
from tzlocal import get_localzone

from updates2mqtt.config import NO_KNOWN_IMAGE, Selector, VersionPolicy

VERSION_RE = r"[vVr]?[0-9]+(\.[0-9]+)*"
# source: https://semver.org/#is-there-a-suggested-regular-expression-regex-to-check-a-semver-string
SEMVER_RE = r"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)(?:-(?P<prerelease>(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?(?:\+(?P<buildmetadata>[0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$"  # noqa: E501

log = structlog.get_logger()


def timestamp(time_value: float | None) -> str | None:
    if time_value is None:
        return None
    try:
        return dt.datetime.fromtimestamp(time_value, tz=get_localzone()).isoformat()
    except:  # noqa: E722
        return None


def select_version(
    version_policy: VersionPolicy,
    version: str | None,
    digest: str | None,
    other_version: str | None = None,
    other_digest: str | None = None,
) -> str:
    """Pick the best version string to display based on the version policy and available data

    Falls back to digest if version not reliable or not consistent with current/available version
    """
    if version_policy == VersionPolicy.VERSION and version:
        return version
    if version_policy == VersionPolicy.DIGEST and digest and digest != NO_KNOWN_IMAGE:
        return digest
    if version_policy == VersionPolicy.VERSION_DIGEST and version and digest and digest != NO_KNOWN_IMAGE:
        return f"{version}:{digest}"
    # AUTO or fallback
    if version_policy == VersionPolicy.AUTO and version and re.match(VERSION_RE, version or ""):
        # Smells like semver
        if other_version is None and other_digest is None:
            return version
        if any((re.match(VERSION_RE, other_version or ""), re.match(SEMVER_RE, other_version or ""))) and (
            (version == other_version and digest == other_digest) or (version != other_version and digest != other_digest)
        ):
            # Only semver if versions and digest consistently same or different
            return version

    if (
        version
        and digest
        and digest != NO_KNOWN_IMAGE
        and ((other_digest is None and other_version is None) or (other_digest is not None and other_version is not None))
    ):
        return f"{version}:{digest}"
    if version and other_version:
        return version
    if digest and digest != NO_KNOWN_IMAGE:
        return digest

    return other_digest or NO_KNOWN_IMAGE


class Selection:
    def __init__(self, selector: Selector, value: str | None) -> None:
        self.result: bool = True
        self.matched: str | None = None
        if value is None:
            self.result = selector.include is None
            return
        if selector.exclude is not None:
            self.result = True
            if any(re.search(pat, value) for pat in selector.exclude):
                self.matched = value
                self.result = False
        if selector.include is not None:
            self.result = False
            if any(re.search(pat, value) for pat in selector.include):
                self.matched = value
                self.result = True

    def __bool__(self) -> bool:
        """Expose the actual boolean so objects can be appropriately truthy"""
        return self.result


class Throttler:
    def __init__(self, api_throttle_pause: int = 30, logger: Any | None = None, semaphore: Event | None = None) -> None:
        self.log: Any = logger or log
        self.pause_api_until: dict[str, float] = {}
        self.api_throttle_pause: int = api_throttle_pause
        self.semaphore = semaphore

    def check_throttle(self, repo_id: str) -> bool:
        if self.semaphore and self.semaphore.is_set():
            return True
        if self.pause_api_until.get(repo_id) is not None:
            if self.pause_api_until[repo_id] < time.time():
                del self.pause_api_until[repo_id]
                self.log.info("%s throttling wait complete", repo_id)
            else:
                self.log.debug("%s throttling has %0.3f secs left", repo_id, self.pause_api_until[repo_id] - time.time())
                return True
        return False

    def throttle(self, repo_id: str, retry_secs: int | None = None, explanation: str | None = None) -> None:
        retry_secs = retry_secs if retry_secs and retry_secs > 0 else self.api_throttle_pause
        self.log.warn("%s throttling requests for %s seconds, %s", repo_id, retry_secs, explanation)
        self.pause_api_until[repo_id] = time.time() + retry_secs
