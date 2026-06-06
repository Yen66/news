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
    "stocks", "shares", "equity", "equities", "treasury", "yields",
    "fed", "federal reserve", "fomc", "interest rate", "inflation", "cpi",
    "earnings", "ipo", "nvidia", "apple", "microsoft", "tesla", "amazon",
    "google", "alphabet", "meta", "wall street", "recession", "gdp",
}

ALL_KEYWORDS = CRYPTO_MAJORS | CRYPTO_ALTCOINS | MARKET_TERMS

# High-signal terms that raise an item's importance.
HIGH_IMPACT_TERMS = {
    "sec", "fed", "federal reserve", "fomc", "etf", "lawsuit", "ban",
    "hack", "exploit", "halving", "rate cut", "rate hike", "approval",
    "bankruptcy", "default", "all-time high", "crash", "plunge", "surge",
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


def matches_keywords(item: NewsItem) -> bool:
    text = _text_of(item)
    return any(kw in text for kw in ALL_KEYWORDS)


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


def score_impact(item: NewsItem) -> int:
    """Return an updated impact score (does not mutate the item)."""
    text = _text_of(item)
    score = item.impact
    if item.official:
        score += 25
    for term in HIGH_IMPACT_TERMS:
        if term in text:
            score += 10
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
