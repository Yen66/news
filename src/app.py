"""Application wiring: poller loop, processing consumer, web server.

Single process (Render free web service):
- aiohttp server (/ and /health) for the UptimeRobot keep-alive ping;
- a background polling task that checks sources every POLL_INTERVAL_SECONDS;
- a processing consumer that drains the throttled priority queue.

No Redis, no separate worker.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from aiohttp import web

from .ai.factory import build_ai_client
from .ai.writer import PostWriter
from .config import Config
from .db.repository import build_repository
from .pipeline.dedup import Deduplicator
from .pipeline.filters import filter_items
from .pipeline.processor import Processor, ProcessingQueue
from .pipeline.throttle import DailyBudget
from .server import build_app
from .sources.catalog import active_sources
from .sources.feeds import FeedFetcher
from .telegram.client import TelegramClient

log = logging.getLogger(__name__)


class NewsBotApp:
    def __init__(self, config: Config) -> None:
        self._config = config
        self._sources = active_sources()

        self._ai = build_ai_client(config)
        self._writer = PostWriter(self._ai, enable_editor=config.enable_editor)
        self._telegram = TelegramClient(
            config.telegram.bot_token,
            config.telegram.channel_id,
            config.telegram.admin_id,
            dry_run=config.dry_run,
            timeout=config.request_timeout_seconds,
        )
        self._repo = build_repository(config.database_url)
        self._dedup = Deduplicator()
        self._budget = DailyBudget(config.daily_ai_call_budget)
        self._queue = ProcessingQueue(config.queue_max_size)
        self._fetcher = FeedFetcher(timeout=config.request_timeout_seconds)
        self._processor = Processor(
            self._writer, self._telegram, self._repo, self._dedup, self._budget
        )

        self._tasks: list[asyncio.Task] = []
        self._stopping = asyncio.Event()
        self._last_poll_ts: float = time.time()
        self._published_total = 0

    # --- status for /health -------------------------------------------------
    def status(self) -> dict:
        poller_alive = (
            time.time() - self._last_poll_ts
            < max(120, self._config.poll_interval_seconds * 4)
        )
        return {
            "poller_alive": poller_alive,
            "queue_size": self._queue.size,
            "seen_ids": self._dedup.size,
            "published_total": self._published_total,
            "ai_budget_used": self._budget.used,
            "ai_budget_remaining": self._budget.remaining,
            "providers": self._ai.provider_names,
            "sources": [s.id for s in self._sources],
        }

    # --- lifecycle ----------------------------------------------------------
    async def startup(self) -> None:
        await self._repo.connect()
        await self._telegram.start()
        await self._fetcher.start()
        seen_uids, seen_keys = await self._repo.load_seen()
        self._dedup = Deduplicator(seen_uids, seen_keys)
        self._processor = Processor(
            self._writer, self._telegram, self._repo, self._dedup, self._budget
        )
        log.info(
            "Startup complete. Sources=%d, seen=%d, providers=%s",
            len(self._sources),
            self._dedup.size,
            self._ai.provider_names,
        )
        await self._safe_alert("Бот запущен. Источников: %d" % len(self._sources))

    async def shutdown(self) -> None:
        self._stopping.set()
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        await self._fetcher.aclose()
        await self._telegram.aclose()
        await self._ai.aclose()
        await self._repo.aclose()

    async def _safe_alert(self, text: str) -> None:
        try:
            await self._telegram.alert_admin(text)
        except Exception as exc:  # noqa: BLE001 - never crash on alerting
            log.error("Failed to alert admin: %s", exc)

    # --- background loops ---------------------------------------------------
    async def _poll_loop(self) -> None:
        interval = self._config.poll_interval_seconds
        while not self._stopping.is_set():
            self._last_poll_ts = time.time()
            try:
                await self._poll_once()
            except Exception as exc:  # noqa: BLE001 - keep the loop alive
                log.exception("Polling cycle failed")
                await self._safe_alert(f"Ошибка опроса источников: {exc}")
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass

    async def _poll_once(self) -> None:
        raw = await self._fetcher.fetch_all(self._sources)
        kept = filter_items(raw)                 # keyword + ads + opinion gate
        fresh = self._dedup.filter_new(kept)     # exact + fuzzy dedup
        # Sort by impact so high-impact items enter the queue first.
        fresh.sort(key=lambda i: i.impact, reverse=True)
        queued = 0
        for item in fresh:
            if await self._queue.put(item):
                queued += 1
        if queued:
            log.info(
                "Poll: %d raw, %d kept, %d new, %d queued",
                len(raw),
                len(kept),
                len(fresh),
                queued,
            )

    async def _consume_loop(self) -> None:
        while not self._stopping.is_set():
            item = await self._queue.get()
            try:
                published = await self._processor.process_one(item)
                if published:
                    self._published_total += 1
            except Exception as exc:  # noqa: BLE001 - alert + continue
                log.exception("Processing failed for: %s", item.title)
                await self._safe_alert(
                    f"Ошибка обработки новости '{item.title[:80]}': {exc}"
                )
            finally:
                self._queue.task_done()

    # --- web runner ---------------------------------------------------------
    async def run(self) -> None:
        await self.startup()
        self._tasks = [
            asyncio.create_task(self._poll_loop(), name="poller"),
            asyncio.create_task(self._consume_loop(), name="consumer"),
        ]

        app = build_app(self.status)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, host="0.0.0.0", port=self._config.http_port)
        await site.start()
        log.info("HTTP server listening on port %d", self._config.http_port)

        try:
            await self._stopping.wait()
        finally:
            await runner.cleanup()
            await self.shutdown()
