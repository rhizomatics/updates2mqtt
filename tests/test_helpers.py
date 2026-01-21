import time

from updates2mqtt.config import Selector
from updates2mqtt.helpers import Selection, timestamp

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
