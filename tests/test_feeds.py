from src.sources.catalog import Source
from src.sources.feeds import _parse_rss, _parse_telegram

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


def test_parse_telegram_extracts_messages():
    items = _parse_telegram(_TELEGRAM, _src("telegram"))
    assert len(items) == 2
    assert "SEC approves" in items[0].summary
    assert items[0].link == "https://t.me/chan/123"
    assert items[0].guid == "chan/123"
