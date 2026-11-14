"""Supply chain controls for updates, see RFC 0002

- Release history: when each image digest was first seen on this host, persisted so a restart,
  or an update of Updates2MQTT itself, doesn't reset the clock
- Tag moves: a versioned tag, such as `2.0.18`, found pointing at a different digest than before
- Cooldown: how long a release has to be known before it's eligible to update

The image's own `created` timestamp is set by whoever built it, so can't be trusted as a release
time. The first sighting here is the default, and other sources can only make a cooldown longer.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog

log: Any = structlog.get_logger()

HISTORY_FORMAT_VERSION = 1
# per image, enough to cover a few months of a busy floating tag without the file growing unbounded
MAX_DIGESTS_PER_IMAGE = 50
MAX_TAGS_PER_IMAGE = 50

RELEASE_TIME_FIRST_SEEN = "first_seen"
RELEASE_TIME_PUBLISHED = "release_published"

# full x.y.z versions are expected to stay put, shorter ones like `3.13` or `16` roll forward with patch releases
VERSIONED_TAG_RE = re.compile(r"[vV]?\d+\.\d+\.\d+([._+-][0-9A-Za-z._+-]*)?")
DURATION_RE = re.compile(r"\s*(\d+(?:\.\d+)?)\s*([smhdw]?)\s*", re.IGNORECASE)
DURATION_UNITS: dict[str, str] = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days", "w": "weeks", "": "hours"}


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def is_versioned_tag(tag: str | None) -> bool:
    """A full version tag, which ought to be immutable, unlike `latest`, `stable` or rolling `3.13`"""
    return bool(tag and VERSIONED_TAG_RE.fullmatch(tag))


def parse_duration(value: str | float | None) -> dt.timedelta | None:
    """Parse `72h`, `3d`, `1w`, `90m` or `0`, with a plain number taken as hours; None if invalid"""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return dt.timedelta(hours=value) if value >= 0 else None
    match = DURATION_RE.fullmatch(value)
    if not match:
        return None
    return dt.timedelta(**{DURATION_UNITS[match.group(2).lower()]: float(match.group(1))})


def parse_timestamp(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed: dt.datetime = dt.datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)


def iso(value: dt.datetime | None) -> str | None:
    return value.astimezone(dt.UTC).isoformat(timespec="seconds") if value else None


@dataclass
class TagMove:
    tag: str
    previous_digest: str
    digest: str
    moved: dt.datetime

    def as_dict(self) -> dict[str, Any]:
        return {"tag": self.tag, "previous_digest": self.previous_digest, "digest": self.digest, "moved": iso(self.moved)}


@dataclass
class Sighting:
    """What the release history knows about a digest"""

    digest: str
    first_seen: dt.datetime
    tag_move: TagMove | None = None


@dataclass
class ImageHistory:
    digests: dict[str, str] = field(default_factory=dict)  # digest -> first seen, iso format
    tags: dict[str, dict[str, str]] = field(default_factory=dict)  # versioned tag -> digest, since, previous, moved


class ReleaseHistory:
    """First sightings of image digests, and which digest each versioned tag had, persisted as JSON

    A missing, unreadable or corrupt file is safe, every digest is then treated as new so cooldowns start again.
    Saved only when something changes, by writing a temporary file and renaming it over the old one.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path: Path | None = path
        self.images: dict[str, ImageHistory] = {}
        self.lock = threading.Lock()  # analysis runs in worker threads
        self.save_failed: bool = False
        self.load()

    def load(self) -> None:
        if self.path is None or not self.path.exists():
            return
        try:
            raw: Any = json.loads(self.path.read_text())
            if not isinstance(raw, dict) or raw.get("version") != HISTORY_FORMAT_VERSION:
                raise ValueError(f"unsupported format version {raw.get('version') if isinstance(raw, dict) else raw}")
            for image, entry in (raw.get("images") or {}).items():
                self.images[image] = ImageHistory(
                    digests=dict(entry.get("digests") or {}), tags={k: dict(v) for k, v in (entry.get("tags") or {}).items()}
                )
            log.debug("Loaded release history", path=str(self.path), images=len(self.images))
        except Exception as e:
            log.warning("Release history unreadable, starting afresh so cooldowns restart: %s", e, path=str(self.path))
            self.images = {}

    def save(self) -> None:
        if self.path is None:
            return
        payload: dict[str, Any] = {
            "version": HISTORY_FORMAT_VERSION,
            "images": {k: {"digests": v.digests, "tags": v.tags} for k, v in sorted(self.images.items())},
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_name = tempfile.mkstemp(prefix=".release_history.", dir=self.path.parent)
            with os.fdopen(fd, "w") as f:
                json.dump(payload, f, indent=1)
            Path(tmp_name).replace(self.path)
            self.save_failed = False
        except Exception as e:
            if not self.save_failed:
                log.warning(
                    "Unable to save release history, cooldowns will restart after a restart: %s", e, path=str(self.path)
                )
            self.save_failed = True

    def observe(self, image: str, digest: str, tag: str | None = None, now: dt.datetime | None = None) -> Sighting:
        """Record a digest seen for an image, and for a versioned tag, whether it moved"""
        now = now or utcnow()
        changed: bool = False
        with self.lock:
            entry: ImageHistory = self.images.setdefault(image, ImageHistory())
            first_seen: dt.datetime | None = parse_timestamp(entry.digests.get(digest))
            if first_seen is None:
                first_seen = now
                entry.digests[digest] = iso(now) or ""
                changed = True
                self.prune(entry.digests, MAX_DIGESTS_PER_IMAGE)

            tag_move: TagMove | None = None
            if is_versioned_tag(tag) and tag is not None:
                tag_entry: dict[str, str] | None = entry.tags.get(tag)
                if tag_entry is None:
                    entry.tags[tag] = {"digest": digest, "since": iso(now) or ""}
                    changed = True
                    self.prune(entry.tags, MAX_TAGS_PER_IMAGE, key="since")
                elif tag_entry.get("digest") != digest:
                    previous: str = tag_entry.get("digest", "")
                    entry.tags[tag] = {"digest": digest, "since": iso(now) or "", "previous": previous, "moved": iso(now) or ""}
                    changed = True
                    log.info(
                        "Versioned tag now points to a different digest", image=image, tag=tag, previous=previous, digest=digest
                    )
                if entry.tags[tag].get("previous"):
                    tag_move = TagMove(
                        tag=tag,
                        previous_digest=entry.tags[tag]["previous"],
                        digest=entry.tags[tag]["digest"],
                        moved=parse_timestamp(entry.tags[tag].get("moved")) or now,
                    )
            if changed:
                self.save()
        return Sighting(digest=digest, first_seen=first_seen, tag_move=tag_move)

    @staticmethod
    def prune(entries: dict[str, Any], limit: int, key: str | None = None) -> None:
        """Drop the oldest entries beyond the limit"""
        if len(entries) <= limit:
            return

        def when(item: tuple[str, Any]) -> str:
            return str(item[1].get(key, "") if key else item[1])

        for name, _ in sorted(entries.items(), key=when)[: len(entries) - limit]:
            del entries[name]


@dataclass
class CooldownStatus:
    """How long a release has to wait before it's eligible to update, and whether it's still waiting"""

    policy: str
    duration: dt.timedelta
    release_time: dt.datetime
    release_time_source: str
    enforced: bool = False

    @property
    def until(self) -> dt.datetime:
        return self.release_time + self.duration

    def active(self, now: dt.datetime | None = None) -> bool:
        return (now or utcnow()) < self.until

    def as_dict(self, now: dt.datetime | None = None) -> dict[str, Any]:
        return {
            "policy": self.policy,
            "release_time": iso(self.release_time),
            "release_time_source": self.release_time_source,
            "until": iso(self.until),
            "active": self.active(now),
            "enforced": self.enforced,
        }


def evaluate_cooldown(
    policy: str, duration: dt.timedelta, first_seen: dt.datetime, published: dt.datetime | None = None
) -> CooldownStatus:
    """Cooldown runs from first sighting, and other sources can only push it later, never earlier"""
    release_time: dt.datetime = first_seen
    source: str = RELEASE_TIME_FIRST_SEEN
    if published is not None and published > first_seen:
        release_time = published
        source = RELEASE_TIME_PUBLISHED
    return CooldownStatus(policy=policy, duration=duration, release_time=release_time, release_time_source=source)
