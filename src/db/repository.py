"""Repository layer over Postgres (Neon) with an in-memory fallback.

Two tables:
- ``sent_news``  — dedup ledger (uid + story key) so restarts don't repost;
- ``archive``    — full archive of every published post with metadata.

If ``DATABASE_URL`` is empty (e.g. local dev or tests) we transparently use
an in-memory repository so the bot is still runnable without a database.
The public interface is identical, so the rest of the code never cares which
backend is active.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import List, Optional, Set, Tuple

from ..models import NewsItem, Post

log = logging.getLogger(__name__)


class Repository(ABC):
    @abstractmethod
    async def connect(self) -> None: ...

    @abstractmethod
    async def aclose(self) -> None: ...

    @abstractmethod
    async def load_seen(self) -> Tuple[Set[str], Set[str]]:
        """Return ``(seen_uids, seen_story_keys)`` for dedup bootstrap."""

    @abstractmethod
    async def mark_sent(self, item: NewsItem) -> None: ...

    @abstractmethod
    async def archive_post(self, post: Post) -> None: ...

    # --- pre-event alert dedup --------------------------------------------
    @abstractmethod
    async def load_fired_alerts(self) -> Set[Tuple[str, str]]:
        """Return ``{(event_id, offset_label), …}`` already fired."""

    @abstractmethod
    async def alert_fired(self, event_id: str, offset_label: str) -> bool:
        """True if this (event, offset) alert was already recorded."""

    @abstractmethod
    async def mark_alert_fired(
        self, event_id: str, offset_label: str, status: str = "sent"
    ) -> bool:
        """Record an alert as fired. Returns True if newly inserted, False if
        it was already present (idempotent — safe under retries/restarts)."""


class InMemoryRepository(Repository):
    """Zero-dependency fallback. State is lost on restart (no DB)."""

    def __init__(self) -> None:
        self._uids: Set[str] = set()
        self._keys: Set[str] = set()
        self.archived: List[Post] = []
        self._fired_alerts: Set[Tuple[str, str]] = set()

    async def connect(self) -> None:
        log.warning(
            "DATABASE_URL not set — using in-memory store. Deduplication will "
            "NOT survive restarts. Set DATABASE_URL (Neon) for production."
        )

    async def aclose(self) -> None:
        pass

    async def load_seen(self) -> Tuple[Set[str], Set[str]]:
        return set(self._uids), set(self._keys)

    async def mark_sent(self, item: NewsItem) -> None:
        self._uids.add(item.uid)
        self._keys.add(item.dedup_key)

    async def archive_post(self, post: Post) -> None:
        self.archived.append(post)

    async def load_fired_alerts(self) -> Set[Tuple[str, str]]:
        return set(self._fired_alerts)

    async def alert_fired(self, event_id: str, offset_label: str) -> bool:
        return (event_id, offset_label) in self._fired_alerts

    async def mark_alert_fired(
        self, event_id: str, offset_label: str, status: str = "sent"
    ) -> bool:
        key = (event_id, offset_label)
        if key in self._fired_alerts:
            return False
        self._fired_alerts.add(key)
        return True


def _rowcount_from_status(status: str) -> int:
    """Parse the affected-row count from an asyncpg command status string.

    e.g. ``"INSERT 0 1"`` -> 1, ``"INSERT 0 0"`` (ON CONFLICT no-op) -> 0.
    """
    try:
        return int(status.split()[-1])
    except (ValueError, IndexError, AttributeError):
        return 0


_SCHEMA = """
CREATE TABLE IF NOT EXISTS sent_news (
    uid          TEXT PRIMARY KEY,
    story_key    TEXT NOT NULL,
    source_id    TEXT NOT NULL,
    title        TEXT NOT NULL,
    link         TEXT NOT NULL,
    sent_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS sent_news_story_key_idx ON sent_news (story_key);

CREATE TABLE IF NOT EXISTS archive (
    id            BIGSERIAL PRIMARY KEY,
    uid           TEXT NOT NULL,
    source_id     TEXT NOT NULL,
    source_name   TEXT NOT NULL,
    title         TEXT NOT NULL,
    link          TEXT NOT NULL,
    body          TEXT NOT NULL,
    official      BOOLEAN NOT NULL DEFAULT false,
    impact        INTEGER NOT NULL DEFAULT 0,
    provider_used TEXT NOT NULL DEFAULT '',
    editor_used   BOOLEAN NOT NULL DEFAULT false,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Pre-event alert dedup ledger. The composite primary key is the duplicate
-- guard: a given (event, offset) can be recorded exactly once, so retries,
-- overlapping ticks and restarts can never double-send.
CREATE TABLE IF NOT EXISTS event_alerts (
    event_id      TEXT NOT NULL,
    offset_label  TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'sent',
    fired_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (event_id, offset_label)
);
"""


class PostgresRepository(Repository):
    """asyncpg-backed repository for Neon (or any Postgres)."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._pool = None

    async def connect(self) -> None:
        import asyncpg

        self._pool = await asyncpg.create_pool(
            self._dsn, min_size=1, max_size=4
        )
        async with self._pool.acquire() as conn:
            await conn.execute(_SCHEMA)
        log.info("Connected to Postgres and ensured schema.")

    async def aclose(self) -> None:
        if self._pool is not None:
            await self._pool.close()

    async def load_seen(self) -> Tuple[Set[str], Set[str]]:
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("SELECT uid, story_key FROM sent_news")
        uids = {r["uid"] for r in rows}
        keys = {r["story_key"] for r in rows}
        log.info("Loaded %d seen ids from Postgres.", len(uids))
        return uids, keys

    async def mark_sent(self, item: NewsItem) -> None:
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO sent_news (uid, story_key, source_id, title, link)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (uid) DO NOTHING
                """,
                item.uid,
                item.dedup_key,
                item.source_id,
                item.title[:500],
                item.link[:1000],
            )

    async def archive_post(self, post: Post) -> None:
        assert self._pool is not None
        item = post.item
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO archive (
                    uid, source_id, source_name, title, link, body,
                    official, impact, provider_used, editor_used, created_at
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
                """,
                item.uid,
                item.source_id,
                item.source_name,
                item.title[:500],
                item.link[:1000],
                post.body,
                post.official,
                item.impact,
                post.provider_used,
                post.editor_used,
                post.created_at,
            )

    async def load_fired_alerts(self) -> Set[Tuple[str, str]]:
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT event_id, offset_label FROM event_alerts"
            )
        return {(r["event_id"], r["offset_label"]) for r in rows}

    async def alert_fired(self, event_id: str, offset_label: str) -> bool:
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT 1 FROM event_alerts "
                "WHERE event_id = $1 AND offset_label = $2",
                event_id,
                offset_label,
            )
        return row is not None

    async def mark_alert_fired(
        self, event_id: str, offset_label: str, status: str = "sent"
    ) -> bool:
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                """
                INSERT INTO event_alerts (event_id, offset_label, status)
                VALUES ($1, $2, $3)
                ON CONFLICT (event_id, offset_label) DO NOTHING
                """,
                event_id,
                offset_label,
                status,
            )
        return _rowcount_from_status(result) > 0


def build_repository(database_url: str) -> Repository:
    if database_url:
        return PostgresRepository(database_url)
    return InMemoryRepository()
