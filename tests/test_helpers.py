import time
from datetime import timedelta
from unittest.mock import Mock

from httpx import Response

from updates2mqtt.config import Selector
from updates2mqtt.helpers import APIStats, Selection, timestamp

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
    assert stats.elapsed == 0.25
    assert stats.average_elapsed() == 0.25


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


def test_api_stats_tick_failed_response() -> None:
    """APIStats.tick should track failed responses by status code"""
    stats = APIStats()
    response = _mock_response(status_code=500)

    stats.tick(response)

    assert stats.fetches == 1
    assert 500 in stats.failed
    assert stats.failed[500] == 1


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
    assert stats.elapsed == 2.25


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

    assert stats.hit_ratio() == 1.0


def test_api_stats_hit_ratio_mixed() -> None:
    """APIStats.hit_ratio should calculate correct ratio"""
    stats = APIStats()
    stats.tick(_mock_response(from_cache=True))
    stats.tick(_mock_response(from_cache=False))
    stats.tick(_mock_response(from_cache=True))
    stats.tick(_mock_response(from_cache=False))

    assert stats.hit_ratio() == 0.5


def test_api_stats_average_elapsed_calculation() -> None:
    """APIStats.average_elapsed should calculate correct average"""
    stats = APIStats()
    stats.tick(_mock_response(elapsed_seconds=1.0))
    stats.tick(_mock_response(elapsed_seconds=2.0))
    stats.tick(_mock_response(elapsed_seconds=3.0))

    assert stats.average_elapsed() == 2.0
