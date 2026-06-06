"""The list of news sources.

Kept deliberately separate from the fetching/processing code so the source
list can be expanded without touching the core. Each entry is a
:class:`Source`. Prefer English-language outlets — more and faster coverage.

We start with a small, working set (3-4 active RSS sources). Add more by
appending to ``SOURCES`` (flip ``enabled`` to turn one on/off). t.me/s and
reddit/youtube examples are included but disabled by default so the minimum
runs out of the box.

``official=True`` marks primary/authoritative outlets (regulators, exchanges,
company blogs). Those posts get the "Официально" label and the editor pass.
``base_impact`` seeds prioritisation when we are near an AI limit.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class Source:
    id: str
    name: str
    kind: str          # "rss" | "youtube" | "reddit" | "telegram"
    url: str
    category: str      # "crypto" | "markets"
    official: bool = False
    base_impact: int = 40
    enabled: bool = True


# YouTube channel RSS: https://www.youtube.com/feeds/videos.xml?channel_id=<ID>
# Reddit RSS:          https://www.reddit.com/r/<sub>/.rss
# Public Telegram:     handled specially via t.me/s/<channel> (url = channel)
SOURCES: List[Source] = [
    # --- Active minimum set (RSS) ---------------------------------------
    Source(
        id="coindesk",
        name="CoinDesk",
        kind="rss",
        url="https://www.coindesk.com/arc/outboundfeeds/rss/",
        category="crypto",
        official=False,
        base_impact=55,
    ),
    Source(
        id="cointelegraph",
        name="Cointelegraph",
        kind="rss",
        url="https://cointelegraph.com/rss",
        category="crypto",
        official=False,
        base_impact=50,
    ),
    Source(
        id="cnbc-finance",
        name="CNBC Finance",
        kind="rss",
        url="https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000664",
        category="markets",
        official=False,
        base_impact=60,
    ),
    Source(
        id="sec-press",
        name="SEC Press Releases",
        kind="rss",
        url="https://www.sec.gov/news/pressreleases.rss",
        category="markets",
        official=True,   # regulator — primary source
        base_impact=85,
    ),
    # --- Expansion examples (disabled by default) -----------------------
    Source(
        id="reddit-cryptocurrency",
        name="r/CryptoCurrency",
        kind="reddit",
        url="https://www.reddit.com/r/CryptoCurrency/.rss",
        category="crypto",
        base_impact=30,
        enabled=False,
    ),
    Source(
        id="yt-coinbureau",
        name="Coin Bureau (YouTube)",
        kind="youtube",
        # Replace <CHANNEL_ID> with a real channel id to enable.
        url="https://www.youtube.com/feeds/videos.xml?channel_id=UCqK_GSMbpiV8spgD3ZGloSw",
        category="crypto",
        base_impact=35,
        enabled=False,
    ),
    Source(
        id="tg-cointelegraph",
        name="Cointelegraph (Telegram)",
        kind="telegram",
        url="cointelegraph",  # t.me/s/cointelegraph
        category="crypto",
        base_impact=40,
        enabled=False,
    ),
]


def active_sources() -> List[Source]:
    return [s for s in SOURCES if s.enabled]
