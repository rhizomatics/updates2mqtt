import datetime as dt
import re
import time
from threading import Event
from typing import Any

import structlog
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
