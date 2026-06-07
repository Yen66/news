"""Mechanical junk filtering — plain code, no AI.

Decides whether a NewsItem is worth sending to the (expensive) AI step:
- it must match the crypto/markets keyword filter;
- obvious ads and empty "price horoscope" posts are dropped;
- influential-opinion gating for opinion/forecast pieces.

It also bumps an item's ``impact`` score for high-signal keywords so the
queue can prioritise official / high-impact news when near AI limits.
"""
from __future__ import annotations

import re
from typing import Iterable

from ..models import NewsItem

# --- Keyword vocabularies -------------------------------------------------
CRYPTO_MAJORS = {
    "bitcoin", "btc", "ethereum", "eth", "ether", "solana", "sol",
    "xrp", "ripple", "bnb", "dogecoin", "doge", "cardano", "ada",
    "stablecoin", "usdt", "usdc", "tether",
}
CRYPTO_ALTCOINS = {
    "altcoin", "avalanche", "avax", "polkadot", "dot", "chainlink", "link",
    "polygon", "matic", "litecoin", "ltc", "tron", "trx", "shiba", "shib",
    "toncoin", "ton", "aptos", "sui", "arbitrum", "optimism", "near",
    "defi", "nft", "etf", "sec", "blockchain", "crypto", "cryptocurrency",
    "binance", "coinbase", "kraken", "mining", "halving",
}
MARKET_TERMS = {
    "s&p", "s&p 500", "sp500", "nasdaq", "dow jones", "dow", "stock",
    "stocks", "shares", "equity", "equities",
    "earnings", "ipo", "nvidia", "apple", "microsoft", "tesla", "amazon",
    "google", "alphabet", "meta", "wall street", "recession", "gdp",
}

# Global macro / forex / rates / commodities / funds — for 24/7 coverage
# beyond US equities.
MACRO_TERMS = {
    # central banks & policy
    "central bank", "central banks", "federal reserve", "fed", "fomc",
    "ecb", "boj", "bank of japan", "boe", "bank of england", "pboc",
    "interest rate", "interest rates", "rate hike", "rate cut", "rate cuts",
    "rate decision", "monetary policy", "quantitative", "inflation", "cpi",
    "ppi", "jobs report", "payrolls", "unemployment",
    # forex
    "forex", "fx", "eur/usd", "usd/jpy", "gbp/usd", "dollar", "euro",
    "yen", "yuan", "renminbi", "pound", "currency", "devaluation",
    # commodities
    "gold", "xau", "silver", "oil", "brent", "wti", "crude", "commodities",
    # bonds / rates / credit
    "bond", "bonds", "treasury", "treasuries", "yield", "yields",
    "10-year", "credit", "default",
    # funds / flows
    "hedge fund", "hedge funds", "etf", "etfs", "etf flows", "etf inflows",
    "etf outflows", "fund flows", "blackrock", "vanguard", "fidelity",
    "grayscale", "institutional",
}

ALL_KEYWORDS = CRYPTO_MAJORS | CRYPTO_ALTCOINS | MARKET_TERMS | MACRO_TERMS

# High-signal terms that raise an item's importance.
HIGH_IMPACT_TERMS = {
    "sec", "fed", "federal reserve", "fomc", "ecb", "boj", "etf",
    "lawsuit", "ban", "hack", "exploit", "halving", "rate cut",
    "rate hike", "rate decision", "approval", "bankruptcy", "default",
    "all-time high", "crash", "plunge", "surge", "interest rate",
}

# Advertising / low-value noise.
AD_PATTERNS = [
    re.compile(r"\bsponsored\b", re.I),
    re.compile(r"\bpromot(?:ed|ion)\b", re.I),
    re.compile(r"\badvertis", re.I),
    re.compile(r"\bpartner content\b", re.I),
    re.compile(r"\bpress release\b", re.I),  # PR fluff (not regulator pages)
    re.compile(r"\bgiveaway\b", re.I),
    re.compile(r"\bairdrop\b", re.I),
    re.compile(r"\bcasino\b", re.I),
    re.compile(r"\bbest .* to buy\b", re.I),
    re.compile(r"\bprice prediction\b", re.I),
]

# "Price horoscope" — pure price-target speculation with no substance.
HOROSCOPE_PATTERNS = [
    re.compile(r"price prediction", re.I),
    re.compile(r"could (?:hit|reach|soar|surge|explode)", re.I),
    re.compile(r"\bto the moon\b", re.I),
    re.compile(r"\b\d+x\b", re.I),
    re.compile(r"next (?:big|100x|1000x)", re.I),
]

# Opinion/forecast markers — these require an influential author.
OPINION_MARKERS = [
    re.compile(r"\bpredict", re.I),
    re.compile(r"\bforecast", re.I),
    re.compile(r"\bsays\b", re.I),
    re.compile(r"\bbelieves\b", re.I),
    re.compile(r"\bopinion\b", re.I),
    re.compile(r"\bexpects\b", re.I),
    re.compile(r"\bwarns\b", re.I),
]

# People/roles with a track record whose opinions we DO publish.
INFLUENTIAL_AUTHORS = {
    "powell", "yellen", "gensler", "lagarde", "musk", "saylor", "dalio",
    "buffett", "ackman", "wood", "cathie wood", "fink", "larry fink",
    "dimon", "jamie dimon", "draghi", "trump", "cz", "changpeng zhao",
    "armstrong", "brian armstrong", "blackrock", "fidelity", "grayscale",
    "federal reserve", "ecb", "imf", "sec chair", "treasury secretary",
}


def _text_of(item: NewsItem) -> str:
    return f"{item.title} {item.summary}".lower()


def _build_keyword_matcher(keywords):
    """Word-boundary matcher for alphanumeric keywords (avoids matching
    'ada' inside 'Canada' or 'oil' inside 'boil'); symbol-bearing keywords
    like 's&p' or 'eur/usd' fall back to substring matching."""
    words = sorted(
        (k for k in keywords if re.fullmatch(r"[a-z0-9 -]+", k)),
        key=len,
        reverse=True,
    )
    symbols = [k for k in keywords if not re.fullmatch(r"[a-z0-9 -]+", k)]
    pattern = re.compile(
        r"(?<![a-z0-9])(?:" + "|".join(re.escape(w) for w in words) + r")(?![a-z0-9])"
    )
    return pattern, symbols


_KEYWORD_RE, _KEYWORD_SYMBOLS = _build_keyword_matcher(ALL_KEYWORDS)


def matches_keywords(item: NewsItem) -> bool:
    text = _text_of(item)
    if _KEYWORD_RE.search(text):
        return True
    return any(sym in text for sym in _KEYWORD_SYMBOLS)


def is_ad(item: NewsItem) -> bool:
    # Regulator/official sources are never treated as ads.
    if item.official:
        return False
    text = f"{item.title} {item.summary}"
    return any(p.search(text) for p in AD_PATTERNS)


def is_price_horoscope(item: NewsItem) -> bool:
    text = f"{item.title} {item.summary}"
    return any(p.search(text) for p in HOROSCOPE_PATTERNS)


def is_opinion(item: NewsItem) -> bool:
    text = f"{item.title} {item.summary}"
    return any(p.search(text) for p in OPINION_MARKERS)


def has_influential_author(item: NewsItem) -> bool:
    text = _text_of(item)
    return any(name in text for name in INFLUENTIAL_AUTHORS)


_HIGH_IMPACT_RE = re.compile(
    r"(?<![a-z0-9])(?:"
    + "|".join(re.escape(t) for t in sorted(HIGH_IMPACT_TERMS, key=len, reverse=True))
    + r")(?![a-z0-9])"
)


def score_impact(item: NewsItem) -> int:
    """Return an updated impact score (does not mutate the item)."""
    text = _text_of(item)
    score = item.impact
    if item.official:
        score += 25
    score += 10 * len(set(_HIGH_IMPACT_RE.findall(text)))
    return max(0, min(100, score))


def should_publish(item: NewsItem) -> bool:
    """The master mechanical gate. True => worth the AI call."""
    if not matches_keywords(item):
        return False
    if is_ad(item):
        return False
    if is_price_horoscope(item):
        return False
    # Opinions/forecasts only from influential people with a track record.
    if is_opinion(item) and not (item.official or has_influential_author(item)):
        return False
    return True


def filter_items(items: Iterable[NewsItem]) -> list[NewsItem]:
    """Apply the gate and refresh impact scores for survivors."""
    kept: list[NewsItem] = []
    for item in items:
        if should_publish(item):
            item.impact = score_impact(item)
            kept.append(item)
    return kept
