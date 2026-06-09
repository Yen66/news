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
import os
import secrets
import time
from collections import Counter
from datetime import datetime, timezone
from typing import Optional

from aiohttp import web

from .ai.factory import build_ai_client
from .ai.writer import PostWriter
from .config import Config
from .db.repository import build_repository
from .events import CalendarError, EventCalendar, PreEventScheduler
from .pipeline.dedup import Deduplicator
from .pipeline.story import StoryDeduplicator
from .pipeline.filters import (
    filter_items,
    is_historical,
    score_impact,
    should_publish,
)
from .pipeline.processor import Processor, ProcessingQueue
from .pipeline.throttle import DailyBudget
from .server import build_app
from .sources.catalog import Source, active_sources
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
        self._story_dedup = StoryDeduplicator(config.story_dedup_window_hours)
        self._budget = DailyBudget(config.daily_ai_call_budget)
        self._queue = ProcessingQueue(config.queue_max_size)
        self._fetcher = FeedFetcher(timeout=config.request_timeout_seconds)
        self._processor = Processor(
            self._writer, self._telegram, self._repo, self._dedup,
            self._budget, config.ai_call_min_interval_seconds,
        )

        self._tasks: list[asyncio.Task] = []
        self._stopping = asyncio.Event()
        self._last_poll_ts: float = time.time()
        self._published_total = 0
        self._poll_count = 0

        # Pre-event alert subsystem. Gated on the feature flag — if it's
        # off, the calendar is NOT loaded and the scheduler is NOT created,
        # so a misconfigured YAML cannot affect the news pipeline.
        self._pre_event_scheduler: Optional[PreEventScheduler] = None
        if config.enable_pre_event_alerts:
            self._init_pre_event_scheduler()

    def _init_pre_event_scheduler(self) -> None:
        from datetime import timedelta

        try:
            calendar = EventCalendar.load(
                self._config.pre_event_calendar_path
            )
        except CalendarError as exc:
            # A bad calendar must not crash startup — disable the subsystem
            # loudly and keep the news pipeline running.
            log.error(
                "Pre-event calendar failed validation, alerts DISABLED: %s",
                exc,
            )
            return
        self._pre_event_scheduler = PreEventScheduler(
            calendar,
            self._repo,
            self._telegram,
            grace=timedelta(minutes=self._config.pre_event_grace_minutes),
            admin_alerter=self._safe_alert,
        )
        log.info(
            "Pre-event alerts ENABLED: %d event(s), grace=%dmin, tick=%ds",
            len(calendar.events),
            self._config.pre_event_grace_minutes,
            self._config.pre_event_tick_seconds,
        )

    # --- status for /health -------------------------------------------------
    def status(self) -> dict:
        poller_alive = (
            time.time() - self._last_poll_ts
            < max(120, self._config.poll_interval_seconds * 4)
        )
        out = {
            "poller_alive": poller_alive,
            "queue_size": self._queue.size,
            "seen_ids": self._dedup.size,
            "story_window": self._story_dedup.size,
            "published_total": self._published_total,
            "ai_budget_used": self._budget.used,
            "ai_budget_remaining": self._budget.remaining,
            "providers": self._ai.provider_names,
            "sources": [s.id for s in self._sources],
        }
        if self._pre_event_scheduler is not None:
            out["pre_event_alerts"] = self._pre_event_scheduler.status()
        return out

    # --- diagnostics --------------------------------------------------------
    async def test_post(self) -> dict:
        """End-to-end pipeline check, triggered by GET /test-post.

        Fetches one fresh CoinDesk article, BYPASSES the seen-check, writes it
        with the AI and posts it to Telegram, then returns a result summary.
        Does NOT mark the item as seen (so it won't interfere with normal
        dedup). Useful to confirm the AI + Telegram pipeline works end to end.
        """
        coindesk = next(
            (s for s in self._sources if s.id == "coindesk"),
            Source(
                id="coindesk",
                name="CoinDesk",
                kind="rss",
                url="https://www.coindesk.com/arc/outboundfeeds/rss/",
                category="crypto",
                base_impact=55,
            ),
        )
        items = await self._fetcher.fetch_source(coindesk)
        if not items:
            return {"published": False, "error": "no items fetched from CoinDesk"}

        # Run the SAME production filter path (firewall + relevance + impact
        # floor). test-post must never publish anything production would
        # reject — so there is NO fallback to an unfiltered item.
        candidates = filter_items(items, self._config.min_impact_to_publish)
        if not candidates:
            return {
                "published": False,
                "error": "no fetched item passed the production filters",
            }
        item = max(candidates, key=lambda i: i.impact)

        try:
            post = await self._writer.write(item)
        except Exception as exc:  # noqa: BLE001 - report to caller
            return {
                "published": False,
                "stage": "ai_write",
                "title": item.title,
                "link": item.link,
                "error": repr(exc),
            }

        sent = await self._telegram.publish(post.body)
        return {
            "published": bool(sent),
            "stage": "telegram_publish" if not sent else "done",
            "title": item.title,
            "link": item.link,
            "provider_used": post.provider_used,
            "editor_used": post.editor_used,
            "official": post.official,
            "impact": item.impact,
            "body_preview": post.body[:400],
        }

    # --- lifecycle ----------------------------------------------------------
    async def startup(self) -> None:
        tg = self._config.telegram
        log.info(
            "Telegram targets -> channel_id=%r (publish), admin_id=%r (alerts). "
            "Posts go to the channel; alerts DM the admin.",
            tg.channel_id,
            tg.admin_id or "(none)",
        )
        if tg.admin_id:
            log.info(
                "Note: admin alerts require you to send /start to the bot once "
                "from the admin account, or Telegram returns 403 'can't "
                "initiate conversation with a user' (channel posts unaffected)."
            )
        await self._repo.connect()
        await self._telegram.start()
        await self._fetcher.start()
        seen_uids, _seen_keys = await self._repo.load_seen()
        self._dedup = Deduplicator(seen_uids)
        self._processor = Processor(
            self._writer, self._telegram, self._repo, self._dedup,
            self._budget, self._config.ai_call_min_interval_seconds,
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
        log.info("Poller task started (interval=%ds, sources=%d)",
                 interval, len(self._sources))
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
        log.info("Poller task stopped.")

    def _filter_by_age(self, items: list) -> list:
        """Keep only articles published within MAX_ARTICLE_AGE_HOURS.

        Anything without a valid, timezone-aware UTC publication date is
        rejected outright — we never guess the timezone of a naive datetime
        and we never use ``updated`` as a substitute for ``published``.
        Skipped items are marked seen (in-memory) so they are not
        re-evaluated every cycle. Nothing is persisted.
        """
        from datetime import timedelta

        max_hours = self._config.max_article_age_hours
        max_age = timedelta(hours=max_hours)
        now = datetime.now(timezone.utc)
        recent = []
        for item in items:
            pub = item.published
            if pub is None:
                log.info(
                    "age-filter REJECT (no-pubdate) source=%s title=%r",
                    item.source_id, item.title[:80],
                )
                self._dedup.mark(item)
                continue
            if pub.tzinfo is None:
                # Naive timestamps are ambiguous — reject rather than assume.
                # All correct feed paths produce aware UTC datetimes.
                log.warning(
                    "age-filter REJECT (naive-tz) source=%s title=%r pub=%s",
                    item.source_id, item.title[:80], pub.isoformat(),
                )
                self._dedup.mark(item)
                continue
            pub_utc = pub.astimezone(timezone.utc)
            age_h = (now - pub_utc).total_seconds() / 3600.0
            if age_h > max_hours:
                log.info(
                    "age-filter REJECT (too-old) source=%s title=%r "
                    "pub=%s now=%s age_h=%.2f limit_h=%d",
                    item.source_id, item.title[:80],
                    pub_utc.isoformat(), now.isoformat(), age_h, max_hours,
                )
                self._dedup.mark(item)
                continue
            if age_h < 0:
                # Future-dated entries are bogus (parser bug or upstream typo).
                log.warning(
                    "age-filter REJECT (future-dated) source=%s title=%r "
                    "pub=%s now=%s",
                    item.source_id, item.title[:80],
                    pub_utc.isoformat(), now.isoformat(),
                )
                self._dedup.mark(item)
                continue
            log.debug(
                "age-filter ACCEPT source=%s title=%r pub=%s age_h=%.2f",
                item.source_id, item.title[:80], pub_utc.isoformat(), age_h,
            )
            recent.append(item)
        return recent

    async def _poll_once(self) -> None:
        self._poll_count += 1
        cycle = self._poll_count
        raw = await self._fetcher.fetch_all(self._sources)
        by_source = Counter(i.source_id for i in raw)
        # Log the first few article links per source so we can verify the feed
        # content is actually changing between cycles (vs. a stale/cached copy).
        samples: dict[str, list[str]] = {}
        for item in raw:
            bucket = samples.setdefault(item.source_id, [])
            if len(bucket) < 3:
                bucket.append(item.link or item.guid or item.title[:60])
        for src_id, links in samples.items():
            log.info("Poll #%d sample %s: %s", cycle, src_id, links)

        # 1) Age filter — before any processing. Older than the limit (or no
        #    pubDate at all) is marked seen silently and skipped, so archive
        #    spam from a newly-added feed never reaches the AI/channel.
        recent = self._filter_by_age(raw)
        age_skipped = len(raw) - len(recent)

        # Historical-content gate (retrospectives / "in 2022" pieces). Mark
        # these seen so we don't reconsider them every cycle.
        historical_skipped = 0
        non_historical = []
        for item in recent:
            # Official sources (SEC/Fed/ECB) are exempt — a regulator release
            # may legitimately reference an old year.
            if not item.official and is_historical(item):
                self._dedup.mark(item)
                historical_skipped += 1
            else:
                non_historical.append(item)

        # Relevance + impact gate. Items below MIN_IMPACT_TO_PUBLISH (regional
        # noise, generic commentary, catalyst-free move recaps) are rejected
        # here, so only trader-relevant signal reaches the channel.
        relevant = len([i for i in non_historical if should_publish(i)])
        kept = filter_items(
            non_historical, self._config.min_impact_to_publish
        )
        low_impact_skipped = relevant - len(kept)
        fresh = self._dedup.filter_new(kept)     # exact (same-article) dedup
        # Highest-impact first so they win both the per-cycle cap and any
        # cross-source story collision.
        fresh.sort(key=lambda i: i.impact, reverse=True)

        # 2) Cross-source story dedup (6h window) + 3) per-cycle burst cap.
        cap = self._config.max_new_per_cycle
        queued = 0
        story_skipped = 0
        for item in fresh:
            if cap > 0 and queued >= cap:
                break
            if self._story_dedup.is_recent(item):
                story_skipped += 1
                continue
            if await self._queue.put(item):
                self._story_dedup.mark(item)
                queued += 1

        # Log EVERY cycle so the poller's liveness is always visible.
        log.info(
            "Poll #%d: fetched=%d old=%d historical=%d low_impact=%d kept=%d "
            "new=%d story_dup=%d queued=%d (cap=%d min_impact=%d) per_source=%s",
            cycle,
            len(raw),
            age_skipped,
            historical_skipped,
            low_impact_skipped,
            len(kept),
            len(fresh),
            story_skipped,
            queued,
            cap,
            self._config.min_impact_to_publish,
            dict(by_source),
        )
        if not raw:
            log.warning(
                "Poll #%d fetched 0 items from %d sources — sources may be "
                "unreachable/blocked or returning errors (see WARNINGs above).",
                cycle,
                len(self._sources),
            )
        elif not kept:
            log.info(
                "Poll #%d: all %d fetched items were filtered out "
                "(keyword/ads/opinion gate).",
                cycle,
                len(raw),
            )

    async def _pre_event_loop(self) -> None:
        """Tick the pre-event scheduler every PRE_EVENT_TICK_SECONDS.

        Failures inside one tick never kill the loop — they are logged
        and the next tick still runs while inside the grace window.
        """
        assert self._pre_event_scheduler is not None
        interval = self._config.pre_event_tick_seconds
        log.info("Pre-event scheduler task started (interval=%ds)", interval)
        try:
            await self._pre_event_scheduler.hydrate()
        except Exception as exc:  # noqa: BLE001
            log.exception("Pre-event hydrate failed; alerts disabled.")
            await self._safe_alert(f"Pre-event hydrate failed: {exc}")
            return
        while not self._stopping.is_set():
            try:
                await self._pre_event_scheduler.tick()
            except Exception as exc:  # noqa: BLE001 - keep the loop alive
                log.exception("Pre-event tick failed")
                await self._safe_alert(f"Pre-event tick failed: {exc}")
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass
        log.info("Pre-event scheduler task stopped.")

    async def _consume_loop(self) -> None:
        log.info("Consumer task started.")
        while not self._stopping.is_set():
            item = await self._queue.get()
            log.info("Processing item from %s: %s", item.source_id, item.title)
            try:
                published = await self._processor.process_one(item)
                if published:
                    self._published_total += 1
                else:
                    log.info("Item not published (dedup/budget): %s", item.title)
            except Exception as exc:  # noqa: BLE001 - alert + continue
                log.exception("Processing failed for: %s", item.title)
                await self._safe_alert(
                    f"Ошибка обработки новости '{item.title[:80]}': {exc}"
                )
            finally:
                self._queue.task_done()
        log.info("Consumer task stopped.")

    def _supervise(self, task: asyncio.Task) -> None:
        """Log + alert if a background task ever exits unexpectedly."""
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            log.error("Background task %r died with: %s", task.get_name(), exc,
                      exc_info=exc)
            asyncio.create_task(
                self._safe_alert(f"Фоновая задача {task.get_name()} упала: {exc}")
            )
        elif not self._stopping.is_set():
            log.error(
                "Background task %r exited unexpectedly (no exception).",
                task.get_name(),
            )

    # --- web runner ---------------------------------------------------------
    async def run(self) -> None:
        await self.startup()
        self._tasks = [
            asyncio.create_task(self._poll_loop(), name="poller"),
            asyncio.create_task(self._consume_loop(), name="consumer"),
        ]
        if self._pre_event_scheduler is not None:
            self._tasks.append(
                asyncio.create_task(self._pre_event_loop(), name="pre-event")
            )
        for task in self._tasks:
            task.add_done_callback(self._supervise)
        log.info("Background tasks created: %s",
                 [t.get_name() for t in self._tasks])

        # /test-post publishes a real post to the production channel, so it
        # must NOT be reachable anonymously. Require an admin secret via
        # TEST_POST_SECRET; if unset, fall back to a per-process random token
        # that effectively disables the endpoint (501-style: cannot be hit
        # without the operator knowing the secret in advance).
        test_post_secret = os.environ.get("TEST_POST_SECRET", "").strip()
        if not test_post_secret:
            test_post_secret = secrets.token_urlsafe(32)
            log.warning(
                "TEST_POST_SECRET not set; /test-post effectively disabled "
                "until a secret is configured in the environment."
            )
        app = build_app(
            self.status,
            test_post=self.test_post,
            test_post_secret=test_post_secret,
        )
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
