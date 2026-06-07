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


async def test_test_post_runs_pipeline_and_bypasses_seen(monkeypatch):
    app = _app(monkeypatch)
    item = make_item("CoinDesk: Bitcoin ETF inflows surge", source_id="coindesk")

    async def fake_fetch_source(_source):
        return [item]

    monkeypatch.setattr(app._fetcher, "fetch_source", fake_fetch_source)

    # Stub the writer + telegram so no real network/AI is needed.
    class _Post:
        body = "Тестовый пост"
        provider_used = "groq"
        editor_used = False
        official = False

    async def fake_write(_item):
        return _Post()

    published_holder = {}

    async def fake_publish(text):
        published_holder["text"] = text
        return True

    monkeypatch.setattr(app._writer, "write", fake_write)
    monkeypatch.setattr(app._telegram, "publish", fake_publish)

    result = await app.test_post()
    assert result["published"] is True
    assert result["title"] == item.title
    assert published_holder["text"] == "Тестовый пост"
    # Must NOT mark the item as seen.
    assert not app._dedup.is_duplicate(item)


async def test_test_post_reports_no_items(monkeypatch):
    app = _app(monkeypatch)

    async def fake_fetch_source(_source):
        return []

    monkeypatch.setattr(app._fetcher, "fetch_source", fake_fetch_source)
    result = await app.test_post()
    assert result["published"] is False
    assert "error" in result


async def test_poll_once_handles_empty_fetch(monkeypatch):
    app = _app(monkeypatch)

    async def fake_fetch_all(_sources):
        return []

    monkeypatch.setattr(app._fetcher, "fetch_all", fake_fetch_all)
    await app._poll_once()  # must not raise
    assert app._poll_count == 1
    assert app._queue.size == 0
