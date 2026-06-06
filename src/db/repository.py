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


class InMemoryRepository(Repository):
    """Zero-dependency fallback. State is lost on restart (no DB)."""

    def __init__(self) -> None:
        self._uids: Set[str] = set()
        self._keys: Set[str] = set()
        self.archived: List[Post] = []

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


def build_repository(database_url: str) -> Repository:
    if database_url:
        return PostgresRepository(database_url)
    return InMemoryRepository()
