"""Exact deduplication: never post the *same article* twice.

Keyed on the item's ``uid`` (guid/link hash). Seen uids are loaded from
Postgres on startup so a Render restart does not cause duplicates.

Cross-source *story* dedup (the same event reported by several outlets) is
handled separately and with a time window by
:class:`src.pipeline.story.StoryDeduplicator`.
"""
from __future__ import annotations

from typing import Iterable, Set

from ..models import NewsItem


class Deduplicator:
    def __init__(self, seen_uids: Iterable[str] = ()) -> None:
        self._uids: Set[str] = set(seen_uids)

    def is_duplicate(self, item: NewsItem) -> bool:
        return item.uid in self._uids

    def mark(self, item: NewsItem) -> None:
        self._uids.add(item.uid)

    def filter_new(self, items: Iterable[NewsItem]) -> list[NewsItem]:
        """Return only genuinely new items, also collapsing exact duplicates
        (same uid) that appear within the same batch."""
        new: list[NewsItem] = []
        batch_uids: Set[str] = set()
        for item in items:
            if self.is_duplicate(item) or item.uid in batch_uids:
                continue
            batch_uids.add(item.uid)
            new.append(item)
        return new

    @property
    def size(self) -> int:
        return len(self._uids)
