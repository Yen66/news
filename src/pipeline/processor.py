"""The per-item processing pipeline + the throttled processing queue.

Flow per item (see README "PER-ITEM PIPELINE"):
  1) code already fetched feeds and found new items (poller);
  2) code already filtered junk + deduplicated (poller);
  3) AI writes the post — ONE call (here);
  4) optional editor proofread for official/high-impact (inside PostWriter);
  5) code posts to the Telegram channel (here).

The queue is an asyncio.PriorityQueue ordered by impact (descending) so that
when we are near the daily AI budget, official and high-impact news is
processed first.
"""
from __future__ import annotations

import asyncio
import itertools
import logging
from typing import Optional

from ..ai.writer import PostWriter
from ..db.repository import Repository
from ..models import NewsItem
from ..telegram.client import TelegramClient
from .dedup import Deduplicator
from .throttle import DailyBudget

log = logging.getLogger(__name__)


class ProcessingQueue:
    """Priority queue of NewsItems awaiting AI processing + posting."""

    def __init__(self, max_size: int = 200) -> None:
        self._queue: asyncio.PriorityQueue = asyncio.PriorityQueue(max_size)
        # Tie-breaker so NewsItem objects are never compared directly.
        self._counter = itertools.count()

    async def put(self, item: NewsItem) -> bool:
        # Higher impact => smaller sort key => processed first.
        priority = -item.impact
        try:
            self._queue.put_nowait((priority, next(self._counter), item))
            return True
        except asyncio.QueueFull:
            log.warning("Processing queue full, dropping item: %s", item.title)
            return False

    async def get(self) -> NewsItem:
        _, _, item = await self._queue.get()
        return item

    def task_done(self) -> None:
        self._queue.task_done()

    @property
    def size(self) -> int:
        return self._queue.qsize()


class Processor:
    """Consumes the queue: writes posts via AI and publishes them."""

    def __init__(
        self,
        writer: PostWriter,
        telegram: TelegramClient,
        repo: Repository,
        dedup: Deduplicator,
        budget: DailyBudget,
    ) -> None:
        self._writer = writer
        self._telegram = telegram
        self._repo = repo
        self._dedup = dedup
        self._budget = budget

    async def process_one(self, item: NewsItem) -> bool:
        """Process a single item end-to-end. Returns True if published."""
        # Re-check dedup at processing time (the item may have been queued
        # before an identical one was published).
        if self._dedup.is_duplicate(item):
            return False

        # Throttle: if out of AI budget, only official/high-impact survive.
        if self._budget.exhausted and not (item.official or item.impact >= 80):
            log.info("AI budget exhausted, skipping low-impact: %s", item.title)
            return False
        if self._budget.near_limit and item.impact < 50 and not item.official:
            log.info("Near AI budget, skipping low-impact: %s", item.title)
            return False

        try:
            post = await self._writer.write(item)
        except Exception as exc:  # noqa: BLE001 - surfaced as alert by caller
            log.error("Failed to write post for %s: %s", item.title, exc)
            raise

        # Account for the AI call(s): 1 writer + maybe 1 editor.
        self._budget.record(2 if post.editor_used else 1)

        sent = await self._telegram.publish(post.body)
        if not sent:
            # Do NOT mark as seen/sent on failure, so the item is retried on a
            # later cycle instead of being silently lost forever.
            log.error(
                "Telegram publish failed for %s — leaving item unseen for "
                "retry.",
                item.title,
            )
            return False

        # Persist for dedup + archive only after a successful publish.
        self._dedup.mark(item)
        await self._repo.mark_sent(item)
        await self._repo.archive_post(post)
        log.info(
            "Published via %s%s: %s",
            post.provider_used,
            " (+editor)" if post.editor_used else "",
            item.title,
        )
        return True
