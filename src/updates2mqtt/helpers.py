import datetime as dt
import re
import time
from threading import Event
from typing import Any
from urllib.parse import urlparse

import structlog
from hishel import CacheOptions, SpecificationPolicy  # pyright: ignore[reportAttributeAccessIssue]
from hishel.httpx import SyncCacheClient
from httpx import Response
from tzlocal import get_localzone

from updates2mqtt.config import Selector

log = structlog.get_logger()


def timestamp(time_value: float | None) -> str | None:
    if time_value is None:
        return None
    try:
        return dt.datetime.fromtimestamp(time_value, tz=get_localzone()).isoformat()
    except:  # noqa: E722
        return None


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


class ThrottledError(Exception):
    def __init__(self, message: str, retry_secs: int) -> None:
        super().__init__(message)
        self.retry_secs = retry_secs


class Throttler:
    DEFAULT_SITE = "DEFAULT_SITE"

    def __init__(self, api_throttle_pause: int = 30, logger: Any | None = None, semaphore: Event | None = None) -> None:
        self.log: Any = logger or log
        self.pause_api_until: dict[str, float] = {}
        self.api_throttle_pause: int = api_throttle_pause
        self.semaphore = semaphore

    def check_throttle(self, index_name: str | None = None) -> bool:
        if self.semaphore and self.semaphore.is_set():
            return True
        index_name = index_name or self.DEFAULT_SITE
        if self.pause_api_until.get(index_name) is not None:
            if self.pause_api_until[index_name] < time.time():
                del self.pause_api_until[index_name]
                self.log.info("%s throttling wait complete", index_name)
            else:
                self.log.debug("%s throttling has %0.3f secs left", index_name, self.pause_api_until[index_name] - time.time())
                return True
        return False

    def throttle(
        self,
        index_name: str | None = None,
        retry_secs: int | None = None,
        explanation: str | None = None,
        raise_exception: bool = False,
    ) -> None:
        index_name = index_name or self.DEFAULT_SITE
        retry_secs = retry_secs if retry_secs and retry_secs > 0 else self.api_throttle_pause
        self.log.warn("%s throttling requests for %s seconds, %s", index_name, retry_secs, explanation)
        self.pause_api_until[index_name] = time.time() + retry_secs
        if raise_exception:
            raise ThrottledError(explanation or f"{index_name} throttled request", retry_secs)


class CacheMetadata:
    """Cache metadata extracted from hishel response extensions"""

    def __init__(self, response: Response) -> None:
        self.from_cache: bool = response.extensions.get("hishel_from_cache", False)
        self.revalidated: bool = response.extensions.get("hishel_revalidated", False)
        self.created_at: float | None = response.extensions.get("hishel_created_at")
        self.stored: bool = response.extensions.get("hishel_stored", False)
        self.age: float | None = None
        if self.created_at is not None:
            self.age = time.time() - self.created_at

    def __str__(self) -> str:
        """Summarize in a string"""
        return f"cached: {self.from_cache}, revalidated: {self.revalidated}, age:{self.age}, stored:{self.stored}"


class APIStats:
    def __init__(self) -> None:
        self.fetches: int = 0
        self.cached: int = 0
        self.revalidated: int = 0
        self.failed: dict[int, int] = {}
        self.elapsed: float = 0
        self.max_cache_age: float = 0

    def tick(self, response: Response | None) -> None:
        self.fetches += 1
        if response is None:
            self.failed.setdefault(0, 0)
            self.failed[0] += 1
            return
        cache_metadata: CacheMetadata = CacheMetadata(response)
        self.cached += 1 if cache_metadata.from_cache else 0
        self.revalidated += 1 if cache_metadata.revalidated else 0
        if response.elapsed:
            self.elapsed += response.elapsed.microseconds / 1000000
            self.elapsed += response.elapsed.seconds
        if not response.is_success:
            self.failed.setdefault(response.status_code, 0)
            self.failed[response.status_code] += 1
        if cache_metadata.age is not None and (self.max_cache_age is None or cache_metadata.age > self.max_cache_age):
            self.max_cache_age = cache_metadata.age

    def hit_ratio(self) -> float:
        return round(self.cached / self.fetches, 2) if self.cached and self.fetches else 0

    def average_elapsed(self) -> float:
        return round(self.elapsed / self.fetches, 2) if self.elapsed and self.fetches else 0

    def __str__(self) -> str:
        """Log line friendly string summary"""
        return (
            f"fetches: {self.fetches}, cache ratio: {self.hit_ratio():.2%}, revalidated: {self.revalidated}, "
            + f"errors: {', '.join(f'{status_code}:{fails}' for status_code, fails in self.failed.items()) or '0'}, "
            + f"oldest cache hit: {self.max_cache_age:.2f}s, avg elapsed: {self.average_elapsed()}s"
        )


class APIStatsCounter:
    def __init__(self) -> None:
        self.stats_report_interval: int = 100
        self.host_stats: dict[str, APIStats] = {}
        self.fetches: int = 0
        self.log: Any = structlog.get_logger().bind()

    def stats(self, url: str, response: Response | None) -> None:
        try:
            host: str = urlparse(url).hostname or "UNKNOWN"
            api_stats: APIStats = self.host_stats.setdefault(host, APIStats())
            api_stats.tick(response)
            self.fetches += 1
            if self.fetches % self.stats_report_interval == 0:
                self.log.info(
                    "OCI_V2 API Stats Summary\n%s", "\n".join(f"{host} {stats}" for host, stats in self.host_stats.items())
                )
        except Exception as e:
            self.log.warning("Failed to tick stats: %s", e)


def fetch_url(
    url: str,
    cache_ttl: int | None = None,  # default to server responses for cache ttl
    bearer_token: str | None = None,
    response_type: str | list[str] | None = None,
    follow_redirects: bool = False,
    allow_stale: bool = False,
    method: str = "GET",
    api_stats_counter: APIStatsCounter | None = None,
) -> Response | None:
    try:
        headers = [("cache-control", f"max-age={cache_ttl}")]
        if bearer_token:
            headers.append(("Authorization", f"Bearer {bearer_token}"))
        if response_type:
            response_type = [response_type] if isinstance(response_type, str) else response_type
            if response_type and isinstance(response_type, (tuple, list)):
                headers.extend(("Accept", mime_type) for mime_type in response_type)

        cache_policy = SpecificationPolicy(
            cache_options=CacheOptions(
                shared=False,  # Private browser cache
                allow_stale=allow_stale,
            )
        )
        with SyncCacheClient(headers=headers, follow_redirects=follow_redirects, policy=cache_policy) as client:
            log.debug(f"Fetching URL {url}, redirects={follow_redirects}, headers={headers}, cache_ttl={cache_ttl}")
            response: Response = client.request(method=method, url=url, extensions={"hishel_ttl": cache_ttl})
            cache_metadata: CacheMetadata = CacheMetadata(response)
            if not response.is_success:
                log.debug("URL %s fetch returned non-success status: %s, %s", url, response.status_code, cache_metadata.stored)
            elif response:
                log.debug(
                    "URL response: status: %s, cached: %s, revalidated: %s, cache age: %s, stored: %s",
                    response.status_code,
                    cache_metadata.from_cache,
                    cache_metadata.revalidated,
                    cache_metadata.age,
                    cache_metadata.stored,
                )
            if api_stats_counter:
                api_stats_counter.stats(url, response)
            return response
    except Exception as e:
        log.debug("URL %s failed to fetch: %s", url, e)
        if api_stats_counter:
            api_stats_counter.stats(url, None)
    return None


def validate_url(url: str, cache_ttl: int = 300) -> bool:
    response: Response | None = fetch_url(url, method="HEAD", cache_ttl=cache_ttl, follow_redirects=True)
    return response is not None and response.status_code != 404
