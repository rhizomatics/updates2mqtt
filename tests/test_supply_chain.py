import datetime as dt
import json
from pathlib import Path

import pytest

from updates2mqtt.supply_chain import (
    RELEASE_TIME_FIRST_SEEN,
    RELEASE_TIME_PUBLISHED,
    ReleaseHistory,
    evaluate_cooldown,
    is_versioned_tag,
    parse_duration,
    parse_timestamp,
)

T0 = dt.datetime(2026, 11, 1, 12, 0, tzinfo=dt.UTC)
IMAGE = "docker.io/library/eclipse-mosquitto"
DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("72h", dt.timedelta(hours=72)),
        ("3d", dt.timedelta(days=3)),
        ("1w", dt.timedelta(weeks=1)),
        ("90m", dt.timedelta(minutes=90)),
        ("30s", dt.timedelta(seconds=30)),
        ("1.5d", dt.timedelta(days=1.5)),
        (" 2D ", dt.timedelta(days=2)),
        ("12", dt.timedelta(hours=12)),
        (6, dt.timedelta(hours=6)),
        ("0", dt.timedelta(0)),
        ("soon", None),
        ("-1d", None),
        (-1, None),
        (True, None),
        (None, None),
    ],
)
def test_parse_duration(value: str | float | None, expected: dt.timedelta | None) -> None:
    assert parse_duration(value) == expected


@pytest.mark.parametrize(
    ("tag", "expected"),
    [
        ("2.0.18", True),
        ("v1.27.3", True),
        ("1.27.3-alpine", True),
        ("16.4.1-bookworm", True),
        ("latest", False),
        ("stable", False),
        ("3.13", False),
        ("16", False),
        ("nightly", False),
        (None, False),
    ],
)
def test_is_versioned_tag(tag: str | None, expected: bool) -> None:
    assert is_versioned_tag(tag) is expected


def test_parse_timestamp() -> None:
    assert parse_timestamp("2026-11-01T12:00:00Z") == T0
    assert parse_timestamp("2026-11-01T12:00:00") == T0  # naive taken as UTC
    assert parse_timestamp("not a time") is None
    assert parse_timestamp(None) is None


def test_first_seen_kept_and_persisted(tmp_path: Path) -> None:
    path = tmp_path / "release_history.json"
    uut = ReleaseHistory(path)
    assert uut.observe(IMAGE, DIGEST_A, now=T0).first_seen == T0
    assert uut.observe(IMAGE, DIGEST_A, now=T0 + dt.timedelta(days=1)).first_seen == T0

    reloaded = ReleaseHistory(path)
    assert reloaded.observe(IMAGE, DIGEST_A, now=T0 + dt.timedelta(days=2)).first_seen == T0
    assert json.loads(path.read_text())["version"] == 1


def test_in_memory_history_writes_nothing(tmp_path: Path) -> None:
    uut = ReleaseHistory()
    uut.observe(IMAGE, DIGEST_A, now=T0)
    assert list(tmp_path.iterdir()) == []


def test_corrupt_history_starts_afresh(tmp_path: Path) -> None:
    path = tmp_path / "release_history.json"
    path.write_text("{not json")
    uut = ReleaseHistory(path)
    later = T0 + dt.timedelta(days=5)
    # safe failure, the digest counts as new so any cooldown restarts
    assert uut.observe(IMAGE, DIGEST_A, now=later).first_seen == later
    assert json.loads(path.read_text())["images"][IMAGE]["digests"][DIGEST_A]


def test_unsupported_version_starts_afresh(tmp_path: Path) -> None:
    path = tmp_path / "release_history.json"
    path.write_text(json.dumps({"version": 99, "images": {IMAGE: {"digests": {DIGEST_A: "2020-01-01T00:00:00+00:00"}}}}))
    assert ReleaseHistory(path).observe(IMAGE, DIGEST_A, now=T0).first_seen == T0


def test_unwritable_history_still_works(tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("")
    uut = ReleaseHistory(blocker / "release_history.json")  # parent is a file, so can't be created
    assert uut.observe(IMAGE, DIGEST_A, now=T0).first_seen == T0
    assert uut.save_failed


def test_versioned_tag_move_detected_and_remembered(tmp_path: Path) -> None:
    path = tmp_path / "release_history.json"
    uut = ReleaseHistory(path)
    assert uut.observe(IMAGE, DIGEST_A, tag="2.0.18", now=T0).tag_move is None

    moved = uut.observe(IMAGE, DIGEST_B, tag="2.0.18", now=T0 + dt.timedelta(hours=1))
    assert moved.tag_move is not None
    assert moved.tag_move.previous_digest == DIGEST_A
    assert moved.tag_move.digest == DIGEST_B
    assert moved.first_seen == T0 + dt.timedelta(hours=1)  # new digest, so its own clock
    assert moved.tag_move.as_dict()["moved"] == "2026-11-01T13:00:00+00:00"

    # still reported on later scans and after a restart
    again = ReleaseHistory(path).observe(IMAGE, DIGEST_B, tag="2.0.18", now=T0 + dt.timedelta(days=1))
    assert again.tag_move is not None
    assert again.tag_move.previous_digest == DIGEST_A


def test_floating_tag_moves_are_expected() -> None:
    uut = ReleaseHistory()
    uut.observe(IMAGE, DIGEST_A, tag="latest", now=T0)
    assert uut.observe(IMAGE, DIGEST_B, tag="latest", now=T0).tag_move is None


def test_history_pruned_to_newest(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("updates2mqtt.supply_chain.MAX_DIGESTS_PER_IMAGE", 3)
    uut = ReleaseHistory()
    for i in range(5):
        uut.observe(IMAGE, f"sha256:{i:064d}", now=T0 + dt.timedelta(hours=i))
    assert sorted(uut.images[IMAGE].digests) == [f"sha256:{i:064d}" for i in (2, 3, 4)]


def test_cooldown_from_first_seen() -> None:
    uut = evaluate_cooldown("3d", dt.timedelta(days=3), first_seen=T0)
    assert uut.release_time_source == RELEASE_TIME_FIRST_SEEN
    assert uut.until == T0 + dt.timedelta(days=3)
    assert uut.active(T0 + dt.timedelta(days=2))
    assert not uut.active(T0 + dt.timedelta(days=3))
    assert uut.as_dict(T0) == {
        "policy": "3d",
        "release_time": "2026-11-01T12:00:00+00:00",
        "release_time_source": RELEASE_TIME_FIRST_SEEN,
        "until": "2026-11-04T12:00:00+00:00",
        "active": True,
        "enforced": False,
    }


def test_cooldown_published_later_extends() -> None:
    published = T0 + dt.timedelta(days=1)
    uut = evaluate_cooldown("3d", dt.timedelta(days=3), first_seen=T0, published=published)
    assert uut.release_time == published
    assert uut.release_time_source == RELEASE_TIME_PUBLISHED


def test_cooldown_published_earlier_never_shortens() -> None:
    uut = evaluate_cooldown("3d", dt.timedelta(days=3), first_seen=T0, published=T0 - dt.timedelta(days=30))
    assert uut.release_time == T0
    assert uut.release_time_source == RELEASE_TIME_FIRST_SEEN
