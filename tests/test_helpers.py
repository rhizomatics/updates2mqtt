import time
from datetime import timedelta
from unittest.mock import Mock

import pytest
from httpx import Response
from pytest_httpx import HTTPXMock

from updates2mqtt.config import Selector
from updates2mqtt.helpers import APIStats, APIStatsCounter, Selection, humanize_timespan, sanitize_name, timestamp

# === Selection Filtering Tests ===


def test_selection_with_no_selector_rules() -> None:
    """When no include/exclude rules, everything should be selected"""
    selector = Selector(include=None, exclude=None)
    selection = Selection(selector, "any-value")
    assert selection.result is True
    assert selection.matched is None


def test_selection_with_none_value_and_no_include() -> None:
    """When value is None and no include rules, should be selected"""
    selector = Selector(include=None, exclude=None)
    selection = Selection(selector, None)
    assert selection.result is True


def test_selection_with_none_value_and_include_rules() -> None:
    """When value is None and include rules exist, should not be selected"""
    selector = Selector(include=["pattern"], exclude=None)
    selection = Selection(selector, None)
    assert selection.result is False


def test_selection_include_matches() -> None:
    """Include rule should match the value"""
    selector = Selector(include=["nginx.*"], exclude=None)
    selection = Selection(selector, "nginx:latest")
    assert selection.result is True
    assert selection.matched == "nginx:latest"


def test_selection_include_no_match() -> None:
    """Include rule should not match if pattern doesn't match"""
    selector = Selector(include=["nginx.*"], exclude=None)
    selection = Selection(selector, "redis:latest")
    assert selection.result is False
    assert selection.matched is None


def test_selection_exclude_matches() -> None:
    """Exclude rule should block matching values"""
    selector = Selector(include=None, exclude=[".*test.*"])
    selection = Selection(selector, "my-test-container")
    assert selection.result is False
    assert selection.matched == "my-test-container"


def test_selection_exclude_no_match() -> None:
    """Exclude rule should allow non-matching values"""
    selector = Selector(include=None, exclude=[".*test.*"])
    selection = Selection(selector, "production-app")
    assert selection.result is True


def test_selection_include_takes_precedence_over_exclude() -> None:
    """When both include and exclude specified, include is evaluated last"""
    # Value matches both include and exclude - include wins (evaluated last)
    selector = Selector(include=["nginx.*"], exclude=[".*latest"])
    selection = Selection(selector, "nginx:latest")
    assert selection.result is True


def test_selection_exclude_blocks_when_include_doesnt_match() -> None:
    """Exclude can block even when include rules exist but don't match"""
    selector = Selector(include=["nginx.*"], exclude=["redis.*"])
    selection = Selection(selector, "redis:latest")
    # First exclude sets result=True (no match), then include sets result=False (no match)
    assert selection.result is False


def test_selection_multiple_include_patterns() -> None:
    """Multiple include patterns - any match should select"""
    selector = Selector(include=["nginx.*", "redis.*", "postgres.*"], exclude=None)

    selection1 = Selection(selector, "nginx:latest")
    assert selection1.result is True

    selection2 = Selection(selector, "redis:7")
    assert selection2.result is True

    selection3 = Selection(selector, "mysql:8")
    assert selection3.result is False


def test_selection_multiple_exclude_patterns() -> None:
    """Multiple exclude patterns - any match should exclude"""
    selector = Selector(include=None, exclude=[".*test.*", ".*dev.*", ".*staging.*"])

    selection1 = Selection(selector, "my-test-app")
    assert selection1.result is False

    selection2 = Selection(selector, "dev-container")
    assert selection2.result is False

    selection3 = Selection(selector, "production-app")
    assert selection3.result is True


def test_selection_regex_special_chars() -> None:
    """Test regex patterns with special characters"""
    selector = Selector(include=[r"ghcr\.io/.*"], exclude=None)
    selection = Selection(selector, "ghcr.io/myorg/myapp")
    assert selection.result is True


def test_selection_bool_conversion() -> None:
    """Selection should be truthy/falsy based on result"""
    selector_allow = Selector(include=None, exclude=None)
    selection_allow = Selection(selector_allow, "test")
    assert bool(selection_allow) is True
    assert selection_allow.result is True

    selector_block = Selector(include=["other"], exclude=None)
    selection_block = Selection(selector_block, "test")
    assert bool(selection_block) is False
    assert selection_block.result is False


# === timestamp helper function tests ===


def test_timestamp_with_valid_value() -> None:
    """timestamp() should format valid float to ISO string"""
    ts = time.time()
    result = timestamp(ts)
    assert result is not None
    assert "T" in result  # ISO format has T separator


def test_timestamp_with_none() -> None:
    """timestamp() should return None for None input"""
    result = timestamp(None)
    assert result is None


def test_timestamp_with_invalid_value() -> None:
    """timestamp() should return None for invalid values"""
    # Very large number that can't be converted
    result = timestamp(float("inf"))
    assert result is None


# === human_timespan helper function tests ===


def test_human_timespan_seconds_only() -> None:
    assert humanize_timespan(45.5) == "0 mins, 45.5 secs"


def test_human_timespan_minutes() -> None:
    assert humanize_timespan(125) == "2 mins, 5 secs"


def test_human_timespan_hours() -> None:
    assert humanize_timespan(2 * 3600 + 5 * 60) == "2 hours, 5 mins"


def test_human_timespan_days() -> None:
    assert humanize_timespan(3 * 86400 + 4 * 3600) == "3 days, 4 hours"


def test_human_timespan_zero() -> None:
    assert humanize_timespan(0) == "0 mins, 0 secs"


def _mock_response(
    status_code: int = 200,
    elapsed_seconds: float = 0.5,
    from_cache: bool = False,
    revalidated: bool = False,
    created_at: float | None = None,
) -> Response:
    """Create a mock Response with cache extensions for testing APIStats"""
    response = Mock(spec=Response)
    response.status_code = status_code
    response.is_success = 200 <= status_code < 300
    response.elapsed = timedelta(seconds=elapsed_seconds)
    response.extensions = {
        "hishel_from_cache": from_cache,
        "hishel_revalidated": revalidated,
        "hishel_created_at": created_at,
    }
    return response


def test_api_stats_tick_success_response() -> None:
    """APIStats.tick should track successful responses"""
    stats = APIStats()
    response = _mock_response(status_code=200, elapsed_seconds=0.25)

    stats.tick(response)

    assert stats.fetches == 1
    assert stats.cached == 0
    assert stats.failed == {}
    assert stats.elapsed == pytest.approx(0.25)
    assert stats.average_elapsed() == pytest.approx(0.25)


def test_api_stats_tick_cached_response() -> None:
    """APIStats.tick should track cached responses"""
    stats = APIStats()
    response = _mock_response(status_code=200, from_cache=True)

    stats.tick(response)

    assert stats.fetches == 1
    assert stats.cached == 1


def test_api_stats_tick_revalidated_response() -> None:
    """APIStats.tick should track revalidated responses"""
    stats = APIStats()
    response = _mock_response(status_code=200, revalidated=True)

    stats.tick(response)

    assert stats.fetches == 1
    assert stats.revalidated == 1


def test_api_stats_tick_throttled_response() -> None:
    """APIStats.tick should track 429 throttled responses"""
    stats = APIStats()
    response = _mock_response(status_code=429)

    stats.tick(response)

    assert stats.fetches == 1
    assert 429 in stats.failed
    assert stats.failed[429] == 1
    assert "429:1" in str(stats)


def test_api_stats_tick_failed_response() -> None:
    """APIStats.tick should track failed responses by status code"""
    stats = APIStats()
    response = _mock_response(status_code=500)

    stats.tick(response)

    assert stats.fetches == 1
    assert 500 in stats.failed
    assert stats.failed[500] == 1
    assert "500:1" in str(stats)


def test_api_stats_tick_none_response() -> None:
    """APIStats.tick should handle None response"""
    stats = APIStats()

    stats.tick(None)

    assert stats.fetches == 1
    assert 0 in stats.failed
    assert stats.failed[0] == 1


def test_api_stats_tick_multiple_failures_same_code() -> None:
    """APIStats.tick should accumulate failures by status code"""
    stats = APIStats()

    stats.tick(_mock_response(status_code=404))
    stats.tick(_mock_response(status_code=404))
    stats.tick(_mock_response(status_code=500))

    assert stats.fetches == 3
    assert stats.failed[404] == 2
    assert stats.failed[500] == 1


def test_api_stats_tick_accumulates_elapsed_time() -> None:
    """APIStats.tick should accumulate elapsed time from responses"""
    stats = APIStats()

    stats.tick(_mock_response(elapsed_seconds=0.5))
    stats.tick(_mock_response(elapsed_seconds=1.5))
    stats.tick(_mock_response(elapsed_seconds=0.25))

    assert stats.fetches == 3
    assert stats.elapsed == pytest.approx(2.25)


def test_api_stats_tick_tracks_max_cache_age() -> None:
    """APIStats.tick should track maximum cache age"""
    import time

    stats = APIStats()
    now = time.time()

    stats.tick(_mock_response(from_cache=True, created_at=now - 100))
    stats.tick(_mock_response(from_cache=True, created_at=now - 300))
    stats.tick(_mock_response(from_cache=True, created_at=now - 50))

    assert stats.max_cache_age is not None
    assert stats.max_cache_age >= 299  # Allow for small time drift


def test_api_stats_hit_ratio_no_fetches() -> None:
    """APIStats.hit_ratio should return 0 when no fetches"""
    stats = APIStats()

    assert stats.hit_ratio() == 0


def test_api_stats_hit_ratio_no_cache_hits() -> None:
    """APIStats.hit_ratio should return 0 when no cache hits"""
    stats = APIStats()
    stats.tick(_mock_response(from_cache=False))
    stats.tick(_mock_response(from_cache=False))

    assert stats.hit_ratio() == 0


def test_api_stats_hit_ratio_all_cached() -> None:
    """APIStats.hit_ratio should return 1.0 when all responses cached"""
    stats = APIStats()
    stats.tick(_mock_response(from_cache=True))
    stats.tick(_mock_response(from_cache=True))

    assert stats.hit_ratio() == pytest.approx(1.0)


def test_api_stats_hit_ratio_mixed() -> None:
    """APIStats.hit_ratio should calculate correct ratio"""
    stats = APIStats()
    stats.tick(_mock_response(from_cache=True))
    stats.tick(_mock_response(from_cache=False))
    stats.tick(_mock_response(from_cache=True))
    stats.tick(_mock_response(from_cache=False))

    assert stats.hit_ratio() == pytest.approx(0.5)


def test_api_stats_average_elapsed_calculation() -> None:
    """APIStats.average_elapsed should calculate correct average"""
    stats = APIStats()
    stats.tick(_mock_response(elapsed_seconds=1.0))
    stats.tick(_mock_response(elapsed_seconds=2.0))
    stats.tick(_mock_response(elapsed_seconds=3.0))

    assert stats.average_elapsed() == pytest.approx(2.0)


def test_api_stats_counter_handles_bad_url() -> None:
    uut = APIStatsCounter()
    uut.stats("bad_url_to_test", _mock_response())
    assert uut.host_stats["UNKNOWN"].fetches == 1


def test_api_stats_counter_handles_good_url() -> None:
    uut = APIStatsCounter()
    uut.stats("https://docker.io/v3/api/manifest/foo", _mock_response())
    assert uut.host_stats["docker.io"].fetches == 1


def test_sanitize_leaves_good_name_untouched() -> None:
    assert sanitize_name("my_docker_container_23") == "my_docker_container_23"


def test_sanitize_replaces_special_chars() -> None:
    assert sanitize_name("#my_docker_container_23!/45") == "_my_docker_container_23_45"


# === throttling ===


def test_throttler_semaphore_forces_throttle() -> None:
    from threading import Event

    from updates2mqtt.helpers import Throttler

    semaphore = Event()
    uut = Throttler(semaphore=semaphore)
    assert not uut.check_throttle("site")
    semaphore.set()
    assert uut.check_throttle("site")


def test_throttler_pauses_then_expires() -> None:
    from updates2mqtt.helpers import ThrottledError, Throttler

    uut = Throttler(api_throttle_pause=60)
    with pytest.raises(ThrottledError) as exc_info:
        uut.throttle("site", retry_secs=0, raise_exception=True)
    assert exc_info.value.retry_secs == 60
    assert "site throttled request" in str(exc_info.value)
    assert uut.check_throttle("site")
    assert not uut.check_throttle("other")
    uut.pause_api_until["site"] = time.time() - 1
    assert not uut.check_throttle("site")
    assert "site" not in uut.pause_api_until


# === cache metadata and stats ===


def test_cache_metadata_str() -> None:
    from updates2mqtt.helpers import CacheMetadata

    response = Response(200, extensions={"hishel_from_cache": True, "hishel_created_at": time.time() - 5})
    metadata = CacheMetadata(response)
    assert metadata.age is not None
    assert metadata.age >= 5
    assert str(metadata).startswith("cached: True, revalidated: False")


def test_api_stats_challenge_counted_separately() -> None:
    uut = APIStats()
    uut.tick(None, challenge=True)
    assert uut.challenges == 1
    assert uut.failed == {}
    assert "auth challenges: 1" in str(uut)


def test_api_stats_tick_without_elapsed() -> None:
    uut = APIStats()
    response = Mock(spec=Response, extensions={}, elapsed=None, is_success=True)
    uut.tick(response)
    assert uut.elapsed == 0


def test_api_stats_counter_reports_periodically() -> None:
    uut = APIStatsCounter()
    uut.stats_report_interval = 2
    uut.log = Mock()
    uut.stats("https://registry.test/v2/", None)
    uut.log.info.assert_not_called()
    uut.stats("https://registry.test/v2/", None)
    uut.log.info.assert_called_once()


# === fetching ===


def test_fetch_url_sends_auth_and_accept_headers(httpx_mock: HTTPXMock) -> None:
    from updates2mqtt.helpers import fetch_url

    httpx_mock.add_response(url="https://api.test/thing", json={"ok": True})
    counter = APIStatsCounter()
    response = fetch_url(
        "https://api.test/thing",
        cache_ttl=0,
        bearer_token="tok",
        response_type="application/json",
        api_stats_counter=counter,
    )
    assert response is not None
    assert response.json() == {"ok": True}
    sent = httpx_mock.get_requests()[0]
    assert sent.headers["Authorization"] == "Bearer tok"
    assert sent.headers["Accept"] == "application/json"
    assert counter.host_stats["api.test"].fetches == 1


def test_fetch_url_returns_non_success(httpx_mock: HTTPXMock) -> None:
    from updates2mqtt.helpers import fetch_url

    httpx_mock.add_response(url="https://api.test/missing", status_code=404)
    response = fetch_url("https://api.test/missing", response_type=["a/b", "c/d"])
    assert response is not None
    assert response.status_code == 404


def test_fetch_url_failure_counted(httpx_mock: HTTPXMock) -> None:
    import httpx

    from updates2mqtt.helpers import fetch_url

    httpx_mock.add_exception(httpx.ConnectError("refused"))
    counter = APIStatsCounter()
    assert fetch_url("https://api.test/down", api_stats_counter=counter) is None
    assert counter.host_stats["api.test"].failed == {0: 1}


def test_validate_url(httpx_mock: HTTPXMock) -> None:
    from updates2mqtt.helpers import validate_url

    httpx_mock.add_response(url="https://api.test/here", method="HEAD", status_code=200)
    httpx_mock.add_response(url="https://api.test/gone", method="HEAD", status_code=404)
    assert validate_url("https://api.test/here", cache_ttl=0)
    assert not validate_url("https://api.test/gone", cache_ttl=0)


@pytest.mark.parametrize(
    ("content_type", "content", "expected"),
    [
        ("application/json", b'{"a": 1}', {"a": 1}),
        ("application/json", b"{broken", "default"),
        ("application/octet-stream", b'{"b": 2}', {"b": 2}),
        ("application/octet-stream", b"\x1f\x8b binary", "default"),
        ("text/html", b"<html>", "default"),
    ],
)
def test_httpx_json_content(content_type: str, content: bytes, expected: object) -> None:
    from updates2mqtt.helpers import httpx_json_content

    response = Response(200, headers={"content-type": content_type}, content=content)
    assert httpx_json_content(response, default="default") == expected


# === sanitizing ===


def test_sanitize_rejects_empty() -> None:
    with pytest.raises(ValueError, match="cannot be empty"):
        sanitize_name("")


def test_sanitize_without_replacement_can_empty_name() -> None:
    with pytest.raises(ValueError, match="became empty"):
        sanitize_name("!!!", replacement="")


def test_sanitize_truncates_long_names() -> None:
    assert sanitize_name("a" * 100, max_len=10) == "a" * 10


# === processes ===


async def test_run_process_missing_executable() -> None:
    from updates2mqtt.helpers import run_process

    result = await run_process(["/nonexistent/updates2mqtt-test-binary"])
    assert result.returncode is None
    assert not result.ok


async def test_run_process_timeout_kills() -> None:
    from updates2mqtt.helpers import run_process

    result = await run_process(["sleep", "10"], timeout=0.1)
    assert result.returncode is None
    assert "Timed out" in result.stderr


async def test_run_process_cancel_kills() -> None:
    import asyncio

    from updates2mqtt.helpers import run_process

    task = asyncio.create_task(run_process(["sleep", "10"]))
    await asyncio.sleep(0.1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


def test_kill_process_tolerates_exited_process() -> None:
    from updates2mqtt.helpers import kill_process

    finished = Mock(returncode=0)
    kill_process(finished)
    finished.kill.assert_not_called()
    vanished = Mock(returncode=None)
    vanished.kill.side_effect = ProcessLookupError
    kill_process(vanished)
