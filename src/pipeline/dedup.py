"""Deduplication: never post the same story twice.

Two layers:
- exact: the item's ``uid`` (guid/link hash) was already sent;
- fuzzy: the item's ``dedup_key`` (normalised-title hash) matches a story we
  already posted from any source — post once, drop the rest.

Both the seen uids and seen story-keys are loaded from Postgres on startup
so a Render restart does not cause duplicates.
"""
from __future__ import annotations

from typing import Iterable, Set

from ..models import NewsItem


class Deduplicator:
    def __init__(
        self,
        seen_uids: Iterable[str] = (),
        seen_keys: Iterable[str] = (),
    ) -> None:
        self._uids: Set[str] = set(seen_uids)
        self._keys: Set[str] = set(seen_keys)

    def is_duplicate(self, item: NewsItem) -> bool:
        return item.uid in self._uids or item.dedup_key in self._keys

    def mark(self, item: NewsItem) -> None:
        self._uids.add(item.uid)
        self._keys.add(item.dedup_key)

    def filter_new(self, items: Iterable[NewsItem]) -> list[NewsItem]:
        """Return only genuinely new items, also collapsing duplicates that
        appear within the same batch (across sources)."""
        new: list[NewsItem] = []
        batch_keys: Set[str] = set()
        batch_uids: Set[str] = set()
        for item in items:
            if self.is_duplicate(item):
                continue
            if item.uid in batch_uids or item.dedup_key in batch_keys:
                continue
            batch_uids.add(item.uid)
            batch_keys.add(item.dedup_key)
            new.append(item)
        return new

    @property
    def size(self) -> int:
        return len(self._uids)
