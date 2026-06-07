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
# NOTE on verification: feed reachability could not be confirmed from the
# build environment (its network policy blocks outbound HTTP, and several
# publishers' Cloudflare protection returns 403 to non-browser fetchers).
# The runtime fetcher sends a browser User-Agent; each poll logs per-source
# item counts (see app._poll_once), so any feed that does not work on Render
# shows up immediately and can be disabled here. Dead feeds fail gracefully
# (warning + empty list). Reuters RSS was dropped — it was discontinued.
SOURCES: List[Source] = [
    # --- US crypto press ------------------------------------------------
    Source(
        id="coindesk", name="CoinDesk", kind="rss",
        url="https://www.coindesk.com/arc/outboundfeeds/rss/",
        category="crypto", base_impact=55,
    ),
    Source(
        id="cointelegraph", name="Cointelegraph", kind="rss",
        url="https://cointelegraph.com/rss",
        category="crypto", base_impact=50,
    ),
    # --- Global crypto (24/7) -------------------------------------------
    Source(
        id="decrypt", name="Decrypt", kind="rss",
        url="https://decrypt.co/feed",
        category="crypto", base_impact=45,
    ),
    Source(
        id="theblock", name="The Block", kind="rss",
        url="https://www.theblock.co/rss.xml",
        category="crypto", base_impact=55,
    ),
    Source(
        id="cryptoslate", name="CryptoSlate", kind="rss",
        url="https://cryptoslate.com/feed/",
        category="crypto", base_impact=40,
    ),
    Source(
        id="blockworks", name="Blockworks", kind="rss",
        url="https://blockworks.co/feed",
        category="crypto", base_impact=50,
    ),
    Source(
        id="beincrypto", name="BeInCrypto", kind="rss",
        url="https://beincrypto.com/feed/",
        category="crypto", base_impact=40,
    ),
    Source(
        id="bitcoinmagazine", name="Bitcoin Magazine", kind="rss",
        url="https://bitcoinmagazine.com/.rss/full/",
        category="crypto", base_impact=40,
    ),
    Source(
        id="forkast", name="Forkast (Asia-Pacific)", kind="rss",
        url="https://forkast.news/feed/",
        category="crypto", base_impact=45,
    ),
    # --- Global macro / markets ----------------------------------------
    Source(
        id="cnbc-finance", name="CNBC Finance", kind="rss",
        url="https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000664",
        category="markets", base_impact=60,
    ),
    Source(
        id="marketwatch", name="MarketWatch", kind="rss",
        url="https://feeds.marketwatch.com/marketwatch/topstories/",
        category="markets", base_impact=55,
    ),
    Source(
        id="investing", name="Investing.com", kind="rss",
        url="https://www.investing.com/rss/news_25.rss",
        category="markets", base_impact=45,
    ),
    Source(
        id="zerohedge", name="ZeroHedge", kind="rss",
        url="https://feeds.feedburner.com/zerohedge/feed",
        category="markets", base_impact=40,
    ),
    # --- Central banks / regulators (official primary sources) ---------
    Source(
        id="sec-press", name="SEC.gov", kind="rss",
        url="https://www.sec.gov/news/pressreleases.rss",
        category="markets", official=True, base_impact=85,
    ),
    Source(
        id="fed-press", name="Federal Reserve", kind="rss",
        url="https://www.federalreserve.gov/feeds/press_releases.xml",
        category="markets", official=True, base_impact=90,
    ),
    Source(
        id="ecb-news", name="ECB", kind="rss",
        url="https://www.ecb.europa.eu/rss/news.html",
        category="markets", official=True, base_impact=88,
    ),
    # --- Reddit community signals (DISABLED by default) -----------------
    # Reddit aggressively rate-limits / 403s datacenter IPs (Render), and the
    # signal is noisy. Flip enabled=True if you proxy or it works for you.
    Source(
        id="reddit-cryptocurrency", name="r/CryptoCurrency", kind="reddit",
        url="https://www.reddit.com/r/CryptoCurrency/.rss",
        category="crypto", base_impact=25, enabled=False,
    ),
    Source(
        id="reddit-bitcoin", name="r/Bitcoin", kind="reddit",
        url="https://www.reddit.com/r/Bitcoin/.rss",
        category="crypto", base_impact=25, enabled=False,
    ),
    Source(
        id="reddit-investing", name="r/investing", kind="reddit",
        url="https://www.reddit.com/r/investing/.rss",
        category="markets", base_impact=25, enabled=False,
    ),
    Source(
        id="reddit-economics", name="r/economics", kind="reddit",
        url="https://www.reddit.com/r/economics/.rss",
        category="markets", base_impact=25, enabled=False,
    ),
]


def active_sources() -> List[Source]:
    return [s for s in SOURCES if s.enabled]
