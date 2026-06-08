"""End-to-end coverage for the MAX_ARTICLE_AGE_HOURS gate.

Stale articles used to slip through because the RSS parser fell back to
``updated_parsed`` when ``published_parsed`` was missing, and because the
struct_time->datetime conversion silently shifted timestamps by the host's
local-TZ offset. These tests pin down both behaviors and the
``_filter_by_age`` decision matrix.
"""
from datetime import datetime, timedelta, timezone

import pytest

from src.app import NewsBotApp
from src.config import load_config
from src.sources.feeds import _parse_rss
from src.sources.catalog import Source
from tests.conftest import make_item


def _app(monkeypatch):
    for k in ("DATABASE_URL", "GROQ_API_KEY", "CEREBRAS_API_KEY",
              "OPENROUTER_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("DRY_RUN", "true")
    monkeypatch.setenv("BOT_TOKEN", "t")
    monkeypatch.setenv("CHANNEL_ID", "@c")
    return NewsBotApp(load_config())


def _src():
    return Source(id="t", name="T", kind="rss", url="u",
                  category="crypto", base_impact=42)


# --- _filter_by_age decision matrix ----------------------------------------

def test_filter_keeps_one_hour_old(monkeypatch):
    app = _app(monkeypatch)
    now = datetime.now(timezone.utc)
    item = make_item("Fresh", published=now - timedelta(hours=1))
    assert app._filter_by_age([item]) == [item]


def test_filter_keeps_23_hours_old(monkeypatch):
    app = _app(monkeypatch)
    now = datetime.now(timezone.utc)
    item = make_item("Just inside limit",
                     published=now - timedelta(hours=23))
    assert app._filter_by_age([item]) == [item]


def test_filter_rejects_25_hours_old(monkeypatch):
    app = _app(monkeypatch)
    now = datetime.now(timezone.utc)
    item = make_item("Just over limit",
                     published=now - timedelta(hours=25))
    assert app._filter_by_age([item]) == []
    assert app._dedup.is_duplicate(item)  # marked seen


def test_filter_rejects_seven_days_old(monkeypatch):
    app = _app(monkeypatch)
    now = datetime.now(timezone.utc)
    item = make_item("Week old", published=now - timedelta(days=7))
    assert app._filter_by_age([item]) == []
    assert app._dedup.is_duplicate(item)


def test_filter_rejects_missing_pubdate(monkeypatch):
    app = _app(monkeypatch)
    item = make_item("No date", published=None)
    assert app._filter_by_age([item]) == []
    assert app._dedup.is_duplicate(item)


def test_filter_rejects_naive_datetime(monkeypatch):
    app = _app(monkeypatch)
    # Naive datetime is ambiguous -> rejected (we never guess the TZ).
    item = make_item("Naive", published=datetime.utcnow())
    assert app._filter_by_age([item]) == []
    assert app._dedup.is_duplicate(item)


def test_filter_accepts_non_utc_offset(monkeypatch):
    app = _app(monkeypatch)
    now = datetime.now(timezone.utc)
    # Published 2h ago, expressed in UTC+9 (Tokyo).
    tokyo = timezone(timedelta(hours=9))
    pub = (now - timedelta(hours=2)).astimezone(tokyo)
    item = make_item("Tokyo time", published=pub)
    assert app._filter_by_age([item]) == [item]


def test_filter_rejects_old_article_with_non_utc_offset(monkeypatch):
    app = _app(monkeypatch)
    now = datetime.now(timezone.utc)
    # 30h ago in UTC-5 — must still be rejected regardless of offset.
    eastern = timezone(timedelta(hours=-5))
    pub = (now - timedelta(hours=30)).astimezone(eastern)
    item = make_item("Eastern time, old", published=pub)
    assert app._filter_by_age([item]) == []


def test_filter_rejects_future_dated(monkeypatch):
    app = _app(monkeypatch)
    item = make_item("From the future",
                     published=datetime.now(timezone.utc) + timedelta(hours=2))
    assert app._filter_by_age([item]) == []


# --- Parser: updated_parsed must NOT rescue a stale entry -------------------

_RSS_OLD_PUBLISHED_RECENT_UPDATED = """<?xml version="1.0"?>
<rss version="2.0"
     xmlns:atom="http://www.w3.org/2005/Atom">
<channel><title>T</title>
  <item>
    <title>Old story re-edited today</title>
    <link>https://example.com/x</link>
    <description>d</description>
    <guid>x-1</guid>
    <pubDate>Sat, 18 May 2024 09:00:00 GMT</pubDate>
    <atom:updated>{updated}</atom:updated>
  </item>
</channel></rss>
"""


def test_recently_updated_old_article_is_blocked_by_age_filter(monkeypatch):
    """An entry whose original pubDate is 2+ years ago but whose <updated>
    is now must be rejected. This is the exact failure mode the bug report
    describes."""
    app = _app(monkeypatch)
    now = datetime.now(timezone.utc)
    updated = now.strftime("%a, %d %b %Y %H:%M:%S GMT")
    xml = _RSS_OLD_PUBLISHED_RECENT_UPDATED.format(updated=updated)
    items = _parse_rss(xml, _src())
    assert len(items) == 1
    # Parser must surface the ORIGINAL pubDate, not the recent update.
    assert items[0].published is not None
    assert items[0].published.year == 2024
    # And the age filter must drop it.
    assert app._filter_by_age(items) == []


def test_only_updated_no_published_is_rejected_as_undated(monkeypatch):
    """Entry has only <updated>, no <pubDate>: we must NOT trust <updated>
    as the publication date. The item ends up without a publication date
    and is rejected by the age filter."""
    app = _app(monkeypatch)
    now = datetime.now(timezone.utc)
    updated = now.strftime("%a, %d %b %Y %H:%M:%S GMT")
    xml = (
        '<?xml version="1.0"?>'
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">'
        '<channel><title>T</title><item>'
        '<title>Only updated</title>'
        '<link>https://example.com/only</link>'
        '<description>d</description>'
        '<guid>only-1</guid>'
        f'<atom:updated>{updated}</atom:updated>'
        '</item></channel></rss>'
    )
    items = _parse_rss(xml, _src())
    assert len(items) == 1
    assert items[0].published is None
    assert app._filter_by_age(items) == []
