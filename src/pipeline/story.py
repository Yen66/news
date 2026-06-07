"""Cross-source story deduplication with a sliding time window.

When several outlets cover the same event within a short window, we publish
only the first. Unlike the permanent exact-id dedup, this is time-bounded
(default 6h): the same story key is allowed again after the window so a
genuinely new event that happens to share a key later is not suppressed
forever. State is in-memory only.
"""
from __future__ import annotations

import time
from typing import Dict

from ..models import NewsItem, story_key


class StoryDeduplicator:
    def __init__(self, window_hours: float = 6.0) -> None:
        self._window = window_hours * 3600.0
        self._seen: Dict[str, float] = {}  # story_key -> last-seen epoch secs

    def _prune(self, now: float) -> None:
        cutoff = now - self._window
        stale = [k for k, ts in self._seen.items() if ts < cutoff]
        for k in stale:
            del self._seen[k]

    def is_recent(self, item: NewsItem, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        key = item.dedup_key
        ts = self._seen.get(key)
        return ts is not None and (now - ts) <= self._window

    def mark(self, item: NewsItem, now: float | None = None) -> None:
        now = time.time() if now is None else now
        self._prune(now)
        self._seen[item.dedup_key] = now

    def key_of(self, title: str) -> str:
        return story_key(title)

    @property
    def size(self) -> int:
        return len(self._seen)
