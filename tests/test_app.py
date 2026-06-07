import os

import pytest

from src.app import NewsBotApp
from src.config import load_config
from tests.conftest import make_item


def _app(monkeypatch):
    # In-memory repo (no DATABASE_URL), dry-run, no provider keys needed for
    # _poll_once (it doesn't call the AI).
    for k in ("DATABASE_URL", "GROQ_API_KEY", "CEREBRAS_API_KEY",
              "OPENROUTER_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("DRY_RUN", "true")
    monkeypatch.setenv("BOT_TOKEN", "t")
    monkeypatch.setenv("CHANNEL_ID", "@c")
    return NewsBotApp(load_config())


async def test_poll_once_queues_new_items(monkeypatch):
    app = _app(monkeypatch)
    items = [
        make_item("SEC approves spot bitcoin ETF", official=True, impact=85),
        make_item("Nasdaq closes at record high", impact=60),
        make_item("Local bakery wins award"),  # filtered out (no keywords)
    ]

    async def fake_fetch_all(_sources):
        return items

    monkeypatch.setattr(app._fetcher, "fetch_all", fake_fetch_all)

    await app._poll_once()
    assert app._poll_count == 1
    # 2 relevant items queued, 1 junk filtered.
    assert app._queue.size == 2


async def test_poll_once_dedups_across_cycles(monkeypatch):
    app = _app(monkeypatch)
    item = make_item("Bitcoin rallies above 70k", guid="g1")

    async def fake_fetch_all(_sources):
        return [item]

    monkeypatch.setattr(app._fetcher, "fetch_all", fake_fetch_all)

    await app._poll_once()
    assert app._queue.size == 1
    # Mark as seen (simulate it being processed/persisted) then poll again.
    app._dedup.mark(item)
    await app._poll_once()
    assert app._poll_count == 2
    assert app._queue.size == 1  # no new item queued the second time


async def test_poll_once_handles_empty_fetch(monkeypatch):
    app = _app(monkeypatch)

    async def fake_fetch_all(_sources):
        return []

    monkeypatch.setattr(app._fetcher, "fetch_all", fake_fetch_all)
    await app._poll_once()  # must not raise
    assert app._poll_count == 1
    assert app._queue.size == 0
