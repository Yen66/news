"""Subject-level burst cap (Task 1.1).

A coarse, in-memory rolling-window counter that limits how many items about
the same SUBJECT (e.g. a multi-article SpaceX IPO saga) get queued within a
short period.

Where :class:`StoryDeduplicator` keys on ``story_key(title)`` (so a saga's
multiple headlines with different numbers/wording produce different keys and
never collapse), :class:`SubjectCap` keys on the number-agnostic
``subject_key(title)`` and counts how many items in the same subject have
been admitted in the window. After ``MAX_PER_SUBJECT`` admissions inside
``SUBJECT_CAP_WINDOW_HOURS``, the next item with that subject is capped.

Same in-memory lifecycle as :class:`StoryDeduplicator` (resets on restart).
"""
from __future__ import annotations

import time as _time
from typing import Dict, List, Optional

from ..models import NewsItem, subject_key


class SubjectCap:
    """Count-based rolling-window cap per subject."""

    def __init__(self, window_hours: float, max_per_subject: int) -> None:
        self._window_seconds = float(window_hours) * 3600.0
        self._max = max(0, int(max_per_subject))
        self._stamps: Dict[str, List[float]] = {}

    @property
    def size(self) -> int:
        return sum(len(v) for v in self._stamps.values())

    def _prune(self, key: str, now: float) -> None:
        stamps = self._stamps.get(key)
        if not stamps:
            return
        cutoff = now - self._window_seconds
        fresh = [t for t in stamps if t > cutoff]
        if fresh:
            self._stamps[key] = fresh
        else:
            del self._stamps[key]

    def is_capped(self, item: NewsItem, now: Optional[float] = None) -> bool:
        if self._max == 0:
            return True
        t = _time.time() if now is None else now
        key = subject_key(item.title)
        self._prune(key, t)
        return len(self._stamps.get(key, [])) >= self._max

    def mark(self, item: NewsItem, now: Optional[float] = None) -> None:
        t = _time.time() if now is None else now
        key = subject_key(item.title)
        self._prune(key, t)
        self._stamps.setdefault(key, []).append(t)
