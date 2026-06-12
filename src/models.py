"""Shared domain models used across the pipeline."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

# Coin / asset names normalised to a canonical ticker so that the same story
# from sources that use names vs tickers collapses together
# (e.g. "Bitcoin" and "BTC" -> "btc").
_COIN_ALIASES = {
    "bitcoin": "btc", "btc": "btc",
    "ethereum": "eth", "ether": "eth", "eth": "eth",
    "solana": "sol", "sol": "sol",
    "ripple": "xrp", "xrp": "xrp",
    "dogecoin": "doge", "doge": "doge",
    "cardano": "ada", "ada": "ada",
    "binance": "bnb", "bnb": "bnb",
    "litecoin": "ltc", "ltc": "ltc",
    "polkadot": "dot", "dot": "dot",
    "chainlink": "link", "link": "link",
    "polygon": "matic", "matic": "matic",
    "toncoin": "ton", "ton": "ton",
    "tron": "trx", "trx": "trx",
    "avalanche": "avax", "avax": "avax",
    "stablecoin": "stablecoin", "usdt": "usdt", "tether": "usdt",
    "usdc": "usdc",
    "coinbase": "coin", "coin": "coin",
    "gold": "gold", "oil": "oil", "brent": "oil", "wti": "oil",
    "nasdaq": "nasdaq", "nvidia": "nvda", "nvda": "nvda", "tesla": "tsla",
    "apple": "aapl", "aapl": "aapl",
}

# Generic words ignored in the no-number fallback key.
_STOPWORDS = {
    "the", "and", "for", "with", "from", "this", "that", "after", "amid",
    "into", "over", "says", "say", "could", "will", "have", "has", "are",
    "was", "were", "what", "why", "how", "new", "now", "its", "his", "her",
    "their", "more", "than", "but", "not", "you", "your", "all", "out",
    "как", "что", "это", "для", "при", "над", "под", "его", "она", "они",
}

# Phase 8 — event-synonym canonicalization for the numberless story key.
# Outlets describe the SAME event with interchangeable verbs ("Meta announces"
# vs "Meta unveils"); mapping them to one canonical token lets the dedup
# collapse those retellings without embeddings or external services. Only
# genuine synonyms are grouped — distinct actions stay distinct.
_VERB_SYNONYMS = {
    # announce / reveal a thing
    "announces": "announce", "announced": "announce",
    "announcement": "announce", "unveils": "announce", "unveiled": "announce",
    "unveil": "announce", "reveals": "announce", "revealed": "announce",
    "introduces": "announce", "introduced": "announce", "debuts": "announce",
    "debuted": "announce", "presents": "announce", "presented": "announce",
    # launch / release / go live
    "launches": "launch", "launched": "launch", "releases": "launch",
    "released": "launch", "rollout": "launch", "rolls": "launch",
    # acquire / buy
    "acquires": "acquire", "acquired": "acquire", "acquisition": "acquire",
    "buys": "acquire", "bought": "acquire", "purchases": "acquire",
    "purchased": "acquire", "purchase": "acquire",
    # raise funding
    "raises": "raise", "raised": "raise", "secures": "raise",
    "secured": "raise",
    # approve / reject
    "approves": "approve", "approved": "approve", "approval": "approve",
    "rejects": "reject", "rejected": "reject", "rejection": "reject",
    # legal
    "sues": "sue", "sued": "sue", "lawsuit": "sue",
    "charges": "charge", "charged": "charge",
    # partnership
    "partners": "partner", "partnership": "partner", "partnered": "partner",
    # rate moves
    "hikes": "hike", "hiked": "hike",
}

# Number tokens like $59K, 59,000, 1.2bn, 7,25% -> normalised canonical form.
_NUM_RE = re.compile(
    r"\$?\d[\d.,]*\s*(?:k|m|bn|b|t|млрд|млн|трлн|тыс|thousand|million|billion|trillion)?%?",
    re.IGNORECASE,
)
_MULTIPLIERS = {
    "k": 1_000, "тыс": 1_000, "thousand": 1_000,
    "m": 1_000_000, "млн": 1_000_000, "million": 1_000_000,
    "b": 1_000_000_000, "bn": 1_000_000_000, "млрд": 1_000_000_000,
    "billion": 1_000_000_000,
    "t": 1_000_000_000_000, "трлн": 1_000_000_000_000,
    "trillion": 1_000_000_000_000,
}
_TICKER_RE = re.compile(r"\b[A-Z]{2,5}\b")


def _normalise_number(token: str) -> Optional[str]:
    is_pct = token.endswith("%")
    t = token.rstrip("%").strip().lower().replace("$", "")
    m = re.match(r"^([\d.,]+)\s*([a-zа-я]+)?$", t)
    if not m:
        return None
    digits, suffix = m.group(1), m.group(2)
    # Decide whether commas are thousands separators or a decimal comma.
    if "," in digits and "." not in digits and re.search(r",\d{1,2}$", digits):
        digits = digits.replace(",", ".")          # decimal comma (7,25)
    else:
        digits = digits.replace(",", "")           # thousands (59,000)
    try:
        value = float(digits)
    except ValueError:
        return None
    if suffix in _MULTIPLIERS:
        value *= _MULTIPLIERS[suffix]
    if value == int(value):
        value = int(value)
    return f"{value}%" if is_pct else str(value)


def story_tokens(title: str) -> List[str]:
    """Extract the canonical story tokens used for cross-source dedup.

    Combines normalised numbers (incl. $ amounts and % changes) and asset
    tickers (coin names normalised to tickers). When the title has a numeric
    anchor, that coarse set IS the key (so "BTC drops to $59K" and "Bitcoin
    falls to $59,000" match). Without a number we add significant words so
    unrelated headlines about the same asset do not over-collapse.
    """
    raw = title.strip()
    nums = []
    for m in _NUM_RE.findall(raw):
        n = _normalise_number(m)
        if n is not None:
            nums.append(n)
    tickers = {t.lower() for t in _TICKER_RE.findall(raw)}
    words_lower = re.findall(r"[a-zA-Zа-яёА-ЯЁ]{3,}", raw.lower())
    assets = {_COIN_ALIASES.get(w) for w in words_lower if w in _COIN_ALIASES}
    assets |= {_COIN_ALIASES.get(t, t) for t in tickers}
    assets = {a for a in assets if a}

    base = set(nums) | assets
    if nums:
        tokens = base
    else:
        # Canonicalise event-synonym verbs so "Meta announces X" and "Meta
        # unveils X" produce the same numberless key (Phase 8).
        significant = {
            _VERB_SYNONYMS.get(w, w)
            for w in words_lower
            if len(w) >= 4 and w not in _STOPWORDS
        }
        tokens = base | significant
    return sorted(tokens)


def story_key(title: str) -> str:
    basis = " ".join(story_tokens(title))
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:24]


# Task 1.1 — coarse, NUMBER-AGNOSTIC subject tokens used by the burst cap
# (src/pipeline/subject.py). Where ``story_tokens`` produces a per-headline
# key (different numbers → different keys), ``subject_tokens`` keeps only
# canonical assets plus the single longest proper-noun-looking word in the
# original-cased title, so every "SpaceX IPO ..." headline maps to the same
# subject regardless of the specific number/wording.
def subject_tokens(title: str) -> List[str]:
    raw = title.strip()
    words_lower = re.findall(r"[a-zA-Zа-яёА-ЯЁ]{3,}", raw.lower())
    tickers = {t.lower() for t in _TICKER_RE.findall(raw)}
    assets = {_COIN_ALIASES.get(w) for w in words_lower if w in _COIN_ALIASES}
    # Only known assets — unlike ``story_tokens`` we do NOT keep arbitrary
    # all-caps tokens (else "AI" / "IPO" / "CEO" would each become a
    # standalone subject).
    assets |= {_COIN_ALIASES[t] for t in tickers if t in _COIN_ALIASES}
    assets = {a for a in assets if a}

    # Proper-noun-like tokens: a capital letter followed by 3+ letters of
    # any case in the ORIGINAL title (so "SpaceX", "Zuckerberg", "Иван" all
    # qualify — CamelCase too; all-caps acronyms like "SEC"/"IPO" are too
    # short and do not). Drop stopwords and any token already collapsed into
    # an asset alias. Canonicalise event-synonym verbs so the same
    # announcement under different verbs still collapses.
    proper = re.findall(
        r"\b[A-ZА-ЯЁ][a-zA-Zа-яёА-ЯЁ]{3,}\b", raw
    )
    proper_lower = [
        _VERB_SYNONYMS.get(t.lower(), t.lower())
        for t in proper
        if t.lower() not in _STOPWORDS and t.lower() not in _COIN_ALIASES
    ]

    tokens = set(assets)
    if proper_lower:
        # The single most "significant" token — heuristic: the longest one.
        tokens.add(max(proper_lower, key=len))
    return sorted(tokens)


def subject_key(title: str) -> str:
    """Stable subject hash for burst-cap deduping across a multi-article saga."""
    basis = " ".join(subject_tokens(title))
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:24]


@dataclass
class NewsItem:
    """A single news item fetched from a source, before/after processing."""

    source_id: str            # catalog id of the source, e.g. "coindesk"
    source_name: str          # human-readable, e.g. "CoinDesk"
    source_kind: str          # "rss" | "youtube" | "reddit" | "telegram"
    title: str
    link: str
    summary: str = ""
    published: Optional[datetime] = None
    # Whether the source is an official/primary outlet (regulator, exchange,
    # company blog). Drives the "Официально" label and editor proofread.
    official: bool = False
    # Relative importance 0..100 used for prioritisation when near AI limits.
    impact: int = 0
    guid: Optional[str] = None
    # Set by the filter pipeline when the item announces an UPCOMING speech /
    # testimony / hearing for a market-moving figure. Drives the ⚠️ writer
    # path (forward-looking post) instead of the ⚡️ breaking-news path.
    is_upcoming_speech: bool = False

    @property
    def uid(self) -> str:
        """Stable unique id for deduplication of the *exact* same item."""
        basis = self.guid or self.link or f"{self.source_id}:{self.title}"
        return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:32]

    @property
    def dedup_key(self) -> str:
        """Cross-source story key (see :func:`story_key`).

        "Bitcoin Hits $100K" and "bitcoin hits $100k!!!" collapse together,
        as do "BTC drops to $59K" and "Bitcoin falls to $59,000".
        """
        return story_key(self.title)


@dataclass
class Post:
    """A rendered post ready to be published to Telegram."""

    item: NewsItem
    body: str                     # AI-written substance (Russian)
    official: bool
    provider_used: str
    editor_used: bool = False
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
