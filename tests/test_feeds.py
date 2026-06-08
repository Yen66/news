from datetime import datetime, timezone

from src.sources.catalog import Source
from src.sources.feeds import _parse_rss, _parse_telegram, _struct_to_dt

_RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <title>Test</title>
  <item>
    <title>Bitcoin surges past 70k</title>
    <link>https://example.com/btc</link>
    <description>BTC up sharply on ETF inflows.</description>
    <guid>btc-1</guid>
    <pubDate>Fri, 06 Jun 2026 10:00:00 GMT</pubDate>
  </item>
  <item>
    <title>Nasdaq hits record</title>
    <link>https://example.com/nasdaq</link>
    <description>Tech stocks rally.</description>
    <guid>ndx-1</guid>
  </item>
</channel></rss>
"""

_TELEGRAM = """
<div class="tgme_widget_message" data-post="chan/123">
  <div class="tgme_widget_message_text">Breaking: SEC approves new rule. Details follow.</div>
  <a class="tgme_widget_message_date" href="https://t.me/chan/123"></a>
</div>
<div class="tgme_widget_message" data-post="chan/124">
  <div class="tgme_widget_message_text">Markets calm ahead of Fed decision</div>
  <a class="tgme_widget_message_date" href="https://t.me/chan/124"></a>
</div>
"""


def _src(kind="rss"):
    return Source(
        id="t", name="T", kind=kind, url="u", category="crypto",
        official=False, base_impact=42,
    )


def test_parse_rss_extracts_items():
    items = _parse_rss(_RSS, _src("rss"))
    assert len(items) == 2
    assert items[0].title == "Bitcoin surges past 70k"
    assert items[0].link == "https://example.com/btc"
    assert items[0].impact == 42
    assert items[0].published is not None
    # Second item has no pubDate -> published is None, that's fine.
    assert items[1].guid == "ndx-1"


def test_parse_rss_skips_incomplete():
    bad = '<rss version="2.0"><channel><item><title>No link</title></item></channel></rss>'
    assert _parse_rss(bad, _src()) == []


_RSS_ONLY_UPDATED = """<?xml version="1.0"?>
<rss version="2.0"
     xmlns:atom="http://www.w3.org/2005/Atom"
     xmlns:dc="http://purl.org/dc/elements/1.1/">
<channel><title>T</title>
  <item>
    <title>Old story republished today</title>
    <link>https://example.com/old</link>
    <description>Originally posted weeks ago, just edited.</description>
    <guid>old-1</guid>
    <atom:updated>Mon, 08 Jun 2026 12:00:00 GMT</atom:updated>
  </item>
</channel></rss>
"""

_RSS_BOTH_DATES = """<?xml version="1.0"?>
<rss version="2.0"
     xmlns:atom="http://www.w3.org/2005/Atom">
<channel><title>T</title>
  <item>
    <title>Touched today, written long ago</title>
    <link>https://example.com/both</link>
    <description>x</description>
    <guid>both-1</guid>
    <pubDate>Sat, 24 May 2025 09:00:00 GMT</pubDate>
    <atom:updated>Mon, 08 Jun 2026 12:00:00 GMT</atom:updated>
  </item>
</channel></rss>
"""


def test_parse_rss_ignores_updated_when_published_missing():
    # Critical: ``updated`` must NEVER substitute for the original pub date.
    # Otherwise an old article republished/re-tagged today looks fresh.
    items = _parse_rss(_RSS_ONLY_UPDATED, _src("rss"))
    assert len(items) == 1
    assert items[0].published is None


def test_parse_rss_prefers_published_over_updated():
    items = _parse_rss(_RSS_BOTH_DATES, _src("rss"))
    assert len(items) == 1
    pub = items[0].published
    assert pub is not None
    # Original publication is May 2025, not the June 2026 update timestamp.
    assert pub.year == 2025 and pub.month == 5
    assert pub.tzinfo is not None


def test_parse_rss_pubdate_is_utc_aware():
    items = _parse_rss(_RSS, _src("rss"))
    pub = items[0].published
    assert pub is not None and pub.tzinfo is not None
    # 06 Jun 2026 10:00:00 GMT
    assert pub == datetime(2026, 6, 6, 10, 0, 0, tzinfo=timezone.utc)


def test_struct_to_dt_treats_struct_as_utc_not_local(monkeypatch):
    # Even if the host TZ is not UTC, the conversion must yield UTC.
    monkeypatch.setenv("TZ", "America/Los_Angeles")
    import time as _time
    if hasattr(_time, "tzset"):
        _time.tzset()
    struct = (2026, 6, 6, 10, 0, 0, 5, 157, 0)  # 10:00 UTC
    dt = _struct_to_dt(struct)
    assert dt == datetime(2026, 6, 6, 10, 0, 0, tzinfo=timezone.utc)


def test_parse_telegram_extracts_messages():
    items = _parse_telegram(_TELEGRAM, _src("telegram"))
    assert len(items) == 2
    assert "SEC approves" in items[0].summary
    assert items[0].link == "https://t.me/chan/123"
    assert items[0].guid == "chan/123"
