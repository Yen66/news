"""Mechanical relevance + impact filtering — plain code, no AI.

Two jobs:

1. **Relevance gate** (`should_publish`): is this item even in our universe —
   crypto, central banks, key macro releases, ETF/regulation, US mega-caps and
   major indices? Obvious ads, price horoscopes, pure unsourced opinion and
   retrospectives are dropped here.

2. **Impact scoring** (`score_impact`): a 0-100 signal score used both to
   prioritise the queue AND — via ``filter_items`` and ``DEFAULT_MIN_IMPACT`` —
   to REJECT low-value noise (small regional indexes, generic analyst
   commentary, articles that merely restate a percentage move with no
   catalyst). Quality over quantity: if it doesn't clear the bar, it never
   reaches the channel.

The channel is for crypto + macro traders, not general market-news
aggregation, so the scoring is deliberately opinionated: it BOOSTS macro
releases, central-bank actions, ETF flows, crypto regulation and major
US-market events, and PENALISES obscure markets, opinion pieces and
catalyst-free move summaries.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Iterable

from ..models import NewsItem

# === Relevance vocabularies ===============================================
# TIER 1 — HIGH priority. The core of the channel. A single tier-1 hit is a
# strong signal and earns a large boost.
TIER1_TERMS = {
    # --- crypto majors & core infra ---
    "bitcoin", "btc", "ethereum", "eth", "ether", "solana", "sol",
    "xrp", "ripple", "bnb", "stablecoin", "usdt", "usdc", "tether",
    # --- ETF / regulation / key institutions ---
    "spot etf", "etf flows", "etf inflows", "etf outflows", "etf approval",
    "etf approvals", "etf rejection", "etf rejections", "sec", "cftc",
    "blackrock", "coinbase", "microstrategy", "strategy inc", "binance",
    "grayscale", "crypto regulation", "stablecoin bill", "stablecoin law",
    "genius act", "mica",
    # --- central banks & policymakers ---
    "federal reserve", "the fed", "fomc", "ecb", "boj", "bank of japan",
    "pboc", "people's bank of china", "bank of england", "boe", "powell",
    "lagarde", "ueda",
    # --- macro releases & rates ---
    "cpi", "core cpi", "ppi", "pce", "nfp", "nonfarm", "non-farm",
    "payrolls", "jobs report", "unemployment", "inflation", "interest rate",
    "interest rates", "rate hike", "rate cut", "rate cuts", "rate decision",
    "rate hold", "monetary policy", "treasury yield", "treasury yields",
    "10-year", "2-year", "dxy", "dollar index",
    # --- US mega-caps, major indices, Magnificent 7 ---
    "s&p 500", "s&p500", "sp500", "nasdaq", "dow jones",
    "apple", "microsoft", "nvidia", "amazon", "meta", "alphabet",
    "google", "tesla", "magnificent seven", "magnificent 7",
}

# Geopolitical / sovereign events that move markets. Treated as tier-1 — these
# are catalysts in their own right (tariff shock, war, OPEC quota, sovereign
# default, US-China trade rupture) and must clear the gate the same way a
# Fed decision does.
GEOPOLITICAL_TERMS = {
    "tariff", "tariffs", "trade war", "trade deal",
    "sanctions", "sanctioned", "embargo", "export controls", "export ban",
    "opec", "opec+",
    "sovereign default", "debt default", "credit rating",
    "downgrade us debt", "us downgrade",
    "government shutdown", "debt ceiling",
    "election", "elections", "presidential election",
    "war", "ceasefire", "invasion", "military strike", "missile strike",
    "taiwan", "middle east", "strait of hormuz", "red sea",
    "russia ukraine", "ukraine war", "israel iran", "iran israel",
    "north korea",
}

# Geopolitical events are first-class tier-1 catalysts.
TIER1_TERMS |= GEOPOLITICAL_TERMS

# TIER 2 — MEDIUM priority. Relevant, but a hit alone is a weaker signal.
TIER2_TERMS = {
    # --- large-cap US equities beyond the Mag 7 ---
    "berkshire", "jpmorgan", "jp morgan", "goldman sachs", "morgan stanley",
    "broadcom", "amd", "netflix", "exxon", "chevron", "walmart",
    "eli lilly", "visa", "mastercard", "palantir", "oracle",
    # --- commodities ---
    "gold", "xau", "silver", "oil", "brent", "wti", "crude",
    "natural gas", "copper",
    # --- corporate events ---
    "earnings", "guidance", "merger", "acquisition", "m&a", "buyback",
    "ipo", "bankruptcy", "layoffs", "downgrade", "upgrade", "delisting",
    # --- other crypto assets / events ---
    "altcoin", "defi", "mining", "halving", "hack", "exploit",
    "cardano", "ada", "avalanche", "avax", "polkadot", "dot",
    "chainlink", "link", "litecoin", "dogecoin", "doge", "toncoin", "ton",
    "aptos", "sui", "arbitrum", "optimism", "tron", "trx", "shiba",
    "kraken", "bybit", "okx",
    # --- FX / rates / funds (secondary) ---
    "forex", "fx", "eur/usd", "usd/jpy", "gbp/usd", "euro", "yen",
    "yuan", "renminbi", "pound", "bond", "bonds", "yield", "yields",
    "hedge fund", "hedge funds", "fund flows", "fidelity", "vanguard",
    "institutional",
}

RELEVANT_KEYWORDS = TIER1_TERMS | TIER2_TERMS
# Backwards-compatible alias (referenced in docs / older callers).
ALL_KEYWORDS = RELEVANT_KEYWORDS

# === Catalyst terms — concrete, market-moving actions ======================
# These signal a real event (not a recap or an opinion) and earn a boost.
CATALYST_TERMS = {
    "approves", "approval", "approved", "rejects", "rejected", "rejection",
    "announces", "announced", "unveils", "launches", "launched", "files",
    "filing", "sues", "lawsuit", "charged", "settlement", "fined", "fine",
    "hikes", "cuts", "raises", "slashes", "halts", "suspends", "freezes",
    "bans", "ban", "delays", "postpones",
    "beats", "misses", "record", "all-time high", "plunges", "plunge",
    "crashes", "crash", "soars", "surges", "surge", "tumbles", "spikes",
    "hack", "hacked", "breach", "default", "defaults", "bankruptcy",
    "acquires", "acquired", "stake", "liquidation",
    "resigns", "sanctions",
}

# === Penalty vocabularies =================================================
# Obscure / regional indexes & local markets — noise for a crypto/macro desk.
REGIONAL_NOISE_TERMS = {
    "ftse", "ftse 100", "dax", "cac 40", "cac", "ibex", "ftse mib",
    "aex", "smi", "omx", "wig20", "athex",
    "nikkei", "topix", "hang seng", "shanghai composite", "csi 300",
    "shenzhen", "kospi", "kosdaq", "sensex", "nifty", "nifty 50",
    "asx 200", "asx", "nzx", "set index", "straits times",
    "jakarta", "psei", "vn-index", "klci", "bursa", "tadawul",
    "bovespa", "ibovespa", "merval", "moex", "borsa istanbul",
    "bist 100", "tsx", "egx",
}

# Opinion / analyst commentary markers — soft penalty (the hard opinion gate
# in should_publish handles unsourced predictions).
COMMENTARY_TERMS = {
    "analyst", "analysts", "strategist", "strategists", "outlook",
    "opinion", "commentary", "op-ed", "column", "explainer",
    "what to watch", "here's why", "here is why", "things to know",
    "what to know", "could", "may", "might", "expected to", "poised to",
    "set to", "forecast", "prediction", "predicts", "sees", "view",
}

# "Just describes a move" phrases — routine recaps with no real news.
_ROUTINE_PHRASES = [
    re.compile(r"\bmarket\s+wrap\b", re.I),
    re.compile(r"\bclosing\s+bell\b", re.I),
    re.compile(r"\bmid-?day\b", re.I),
    re.compile(r"\bpre-?market\b", re.I),
    re.compile(r"\bstocks?\s+to\s+watch\b", re.I),
    re.compile(r"\bweek\s+ahead\b", re.I),
    re.compile(r"\bday\s+ahead\b", re.I),
    re.compile(r"\bmarket\s+recap\b", re.I),
    re.compile(r"\bstocks?\s+(?:end|close[ds]?|finish)\s+(?:mixed|flat|higher|lower)\b", re.I),
    re.compile(r"\bwall\s+street\s+(?:wrap|recap)\b", re.I),
]
# A bare "X up/down 0.4%" move with no other signal.
_MOVE_RE = re.compile(
    r"\b(?:up|down|higher|lower|rises?|rose|falls?|fell|gains?|gained|"
    r"drops?|dropped|slips?|slipped|climbs?|climbed|adds?|sheds?|"
    r"loses?|lost|edges?|ticks?)\b[^.]{0,20}?\b\d+(?:\.\d+)?\s*%",
    re.I,
)

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

# Opinion/forecast markers — these require an influential author. Deliberately
# excludes "forecast"/"expects": those appear in factual beat/miss-vs-estimates
# reporting ("hotter than forecast", "above expectations") on hard releases.
OPINION_MARKERS = [
    re.compile(r"\bpredict", re.I),
    re.compile(r"\bsays\b", re.I),
    re.compile(r"\bbelieves\b", re.I),
    re.compile(r"\bopinion\b", re.I),
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

# === Upcoming-speech detection ============================================
# Market-moving figures whose SCHEDULED appearances we want to warn about
# before they happen. INFLUENTIAL_AUTHORS above (Powell/Lagarde/Yellen/...)
# count too — this set adds principals not already there.
SPEECH_FIGURES = {
    "trump", "bessent", "lutnick", "kashkari", "waller", "williams",
    "daly", "bostic", "goolsbee", "barr", "cook", "jefferson", "ueda",
    "centeno", "villeroy", "nagel", "de guindos", "schnabel",
    "treasury secretary", "commerce secretary", "fed chair",
    "ecb president", "sec chair", "sec chairman",
    # Cyrillic aliases (feeds/posts may use Russian spellings).
    "трамп", "пауэлл", "лагард", "йеллен", "бессент", "лютник",
    "гензлер", "уэда",
}
# Language announcing an UPCOMING appearance (case-insensitive).
SPEECH_INTENT_RE = re.compile(
    r"\b(?:"
    r"to\s+(?:speak|address|testify|deliver(?:\s+remarks)?)"
    r"|will\s+(?:speak|address|testify|deliver)"
    r"|(?:is|are)\s+(?:scheduled|expected|set)\s+to\s+"
    r"(?:speak|address|testify|deliver|hold)"
    r"|scheduled\s+(?:speech|remarks|address|testimony|press\s+conference|"
    r"hearing|appearance)"
    r"|(?:senate|house|congressional|confirmation)\s+(?:hearing|testimony)"
    r"|upcoming\s+(?:speech|address|remarks|appearance|hearing|testimony)"
    r"|press\s+conference\s+(?:today|tomorrow|on)"
    r"|выступит|выступление|пресс[-\s]конференци|слушани"
    r")\b",
    re.IGNORECASE,
)

# Past-tense / already-happened markers — used as a title-only guard to drop
# recaps ("Powell spoke yesterday", "Trump addressed reporters").
_SPEECH_PAST_TENSE_RE = re.compile(
    r"\b(?:spoke|addressed|testified|delivered|told\s+reporters|"
    r"said\s+(?:earlier|on|that)|выступил)\b",
    re.IGNORECASE,
)
# Words that re-assert a future framing even alongside a past-tense token.
_SPEECH_FUTURE_HINT_RE = re.compile(
    r"\b(?:will|to\s+\w+|scheduled|expected|upcoming|today|tomorrow|"
    r"завтра|сегодня)\b",
    re.IGNORECASE,
)

# Minimum impact score an item must reach to be published. Tunable via
# MIN_IMPACT_TO_PUBLISH; the default trades volume for signal.
DEFAULT_MIN_IMPACT = 45


def _text_of(item: NewsItem) -> str:
    return f"{item.title} {item.summary}".lower()


def _build_keyword_matcher(keywords):
    """Word-boundary matcher for alphanumeric keywords (avoids matching
    'ada' inside 'Canada' or 'oil' inside 'boil'); symbol-bearing keywords
    like 's&p' or 'eur/usd' fall back to substring matching."""
    words = sorted(
        (k for k in keywords if re.fullmatch(r"[a-z0-9 '-]+", k)),
        key=len,
        reverse=True,
    )
    symbols = [k for k in keywords if not re.fullmatch(r"[a-z0-9 '-]+", k)]
    pattern = re.compile(
        r"(?<![a-z0-9])(?:" + "|".join(re.escape(w) for w in words) + r")(?![a-z0-9])"
    )
    return pattern, symbols


def _matches(text: str, pattern, symbols) -> bool:
    if pattern.search(text):
        return True
    return any(sym in text for sym in symbols)


def _count_distinct(text: str, pattern, symbols) -> int:
    found = set(pattern.findall(text))
    found |= {sym for sym in symbols if sym in text}
    return len(found)


_TIER1_RE, _TIER1_SYM = _build_keyword_matcher(TIER1_TERMS)
_TIER2_RE, _TIER2_SYM = _build_keyword_matcher(TIER2_TERMS)
_RELEVANT_RE, _RELEVANT_SYM = _build_keyword_matcher(RELEVANT_KEYWORDS)
_CATALYST_RE, _CATALYST_SYM = _build_keyword_matcher(CATALYST_TERMS)
_REGIONAL_RE, _REGIONAL_SYM = _build_keyword_matcher(REGIONAL_NOISE_TERMS)
_COMMENTARY_RE, _COMMENTARY_SYM = _build_keyword_matcher(COMMENTARY_TERMS)
_SPEECH_FIGURE_RE, _SPEECH_FIGURE_SYM = _build_keyword_matcher(
    SPEECH_FIGURES | INFLUENTIAL_AUTHORS
)


def is_upcoming_speech(item: NewsItem) -> bool:
    """True if the item announces an UPCOMING appearance by a market-moving
    figure (speech / testimony / hearing / press conference).

    Precision levers:
    - intent language (SPEECH_INTENT_RE) must appear in title or body;
    - a whitelisted figure (or an existing influential author) must be named;
    - a past-tense title with no future hint is rejected (drops recaps).
    """
    title = item.title or ""
    text = f"{title} {item.summary}"
    if not SPEECH_INTENT_RE.search(text):
        return False
    # Title-only past-tense guard: "Powell spoke yesterday" -> drop, unless the
    # title also carries a future framing ("spoke today, will speak tomorrow").
    if _SPEECH_PAST_TENSE_RE.search(title) and not _SPEECH_FUTURE_HINT_RE.search(
        title
    ):
        return False
    low = text.lower()
    return _matches(low, _SPEECH_FIGURE_RE, _SPEECH_FIGURE_SYM)


def matches_keywords(item: NewsItem) -> bool:
    """True if the item touches our universe (crypto / macro / mega-caps).

    Official sources (regulators / central banks) are always relevant even if
    a headline is terse."""
    if item.official:
        return True
    return _matches(_text_of(item), _RELEVANT_RE, _RELEVANT_SYM)


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


# --- Noise detectors (used by scoring) ------------------------------------
def has_tier1(item: NewsItem) -> bool:
    return _matches(_text_of(item), _TIER1_RE, _TIER1_SYM)


def is_regional_noise(item: NewsItem) -> bool:
    """A regional/obscure index or local market with no tier-1 anchor."""
    text = _text_of(item)
    if not _matches(text, _REGIONAL_RE, _REGIONAL_SYM):
        return False
    return not _matches(text, _TIER1_RE, _TIER1_SYM)


def is_commentary(item: NewsItem) -> bool:
    return _matches(_text_of(item), _COMMENTARY_RE, _COMMENTARY_SYM)


def is_routine_move(item: NewsItem) -> bool:
    """A plain recap that merely restates a market move (no catalyst)."""
    text = f"{item.title} {item.summary}"
    if any(p.search(text) for p in _ROUTINE_PHRASES):
        return True
    return bool(_MOVE_RE.search(text))


def score_impact(item: NewsItem) -> int:
    """Return a 0-100 impact/signal score (does not mutate the item).

    Built from the source-seeded base plus tiered relevance and catalyst
    boosts, minus penalties for regional noise, commentary and catalyst-free
    move recaps. ``filter_items`` rejects anything below the publish bar.
    """
    text = _text_of(item)
    score = item.impact  # source-seeded base (catalog base_impact)

    if item.official:
        score += 25

    # Upcoming-speech items are high-priority pre-event warnings.
    if is_upcoming_speech(item):
        score += 25

    tier1 = _count_distinct(text, _TIER1_RE, _TIER1_SYM)
    tier2 = _count_distinct(text, _TIER2_RE, _TIER2_SYM)
    catalysts = _count_distinct(text, _CATALYST_RE, _CATALYST_SYM)

    # Boosts (capped so two strong hits already saturate the signal).
    score += 18 * min(tier1, 2)          # up to +36
    score += 8 * min(tier2, 2)           # up to +16
    score += 10 * min(catalysts, 2)      # up to +20

    # Penalties — only bite when there is no tier-1 anchor, so a genuine
    # Fed/BTC story with a stray analyst quote is not nuked.
    if tier1 == 0:
        if _matches(text, _REGIONAL_RE, _REGIONAL_SYM):
            score -= 30                  # obscure / regional market
        if _matches(text, _COMMENTARY_RE, _COMMENTARY_SYM) and not item.official:
            score -= 15                  # generic analyst commentary
        if catalysts == 0 and (
            any(p.search(text) for p in _ROUTINE_PHRASES)
            or _MOVE_RE.search(text)
        ):
            score -= 25                  # merely restates a move, no catalyst

    # Unsourced opinion with no influential author / official backing.
    if is_opinion(item) and not (item.official or has_influential_author(item)):
        score -= 20

    return max(0, min(100, score))


# --- Historical / retrospective content detection --------------------------
# Phrases that strongly indicate the article's PRIMARY topic is an event from
# years ago (retrospectives, year-in-review pieces, anniversaries).
_HISTORICAL_PHRASES = [
    re.compile(r"\b20(1[0-9]|2[0-4])\s*год\s*ста\w*", re.I),
    re.compile(r"\bв\s+20(1[0-9]|2[0-4])\s+году\b", re.I),
    re.compile(r"\bin\s+20(1[0-9]|2[0-4])\b", re.I),
    re.compile(r"\bback\s+in\s+20(1[0-9]|2[0-4])\b", re.I),
    re.compile(r"\b20(1[0-9]|2[0-4])\s+(?:was|saw|marked|became|brought)\b",
               re.I),
    re.compile(r"\b(?:year|years)\s+ago\b", re.I),
    re.compile(r"\b(?:on\s+this\s+day|throwback|retrospective|"
               r"year[\s-]?in[\s-]?review|anniversary)\b", re.I),
    re.compile(r"\bретроспектив\w*", re.I),
    re.compile(r"\b(?:годовщин\w+|итоги\s+20(1[0-9]|2[0-4]))", re.I),
]

_YEAR_RE = re.compile(r"\b(20[0-9]{2})\b")


def _current_year() -> int:
    return datetime.now(timezone.utc).year


def title_is_historical(item: NewsItem) -> bool:
    """True if the TITLE only mentions years <= current_year - 1 (no recent
    year), implying a retrospective/historical headline."""
    years = {int(y) for y in _YEAR_RE.findall(item.title)}
    if not years:
        return False
    cutoff = _current_year() - 1  # treat last year + earlier as historical
    return all(y <= cutoff for y in years)


def is_historical(item: NewsItem) -> bool:
    """True if the article's PRIMARY topic is an event from 2+ years ago.

    Heuristic: title is retrospective (years <= last year and none current),
    OR the body has a strong retrospective phrase AND no current-year date
    mention (which would mean the old year is just context, not topic).
    """
    if title_is_historical(item):
        return True
    text = f"{item.title} {item.summary}"
    has_retrospective = any(p.search(text) for p in _HISTORICAL_PHRASES)
    if not has_retrospective:
        return False
    cy = _current_year()
    current_years = {str(cy), str(cy - 1)}
    body_years = set(_YEAR_RE.findall(text))
    # If a current/last-year date is mentioned, the old year is likely context.
    if body_years & current_years:
        return False
    return True


def should_publish(item: NewsItem) -> bool:
    """The categorical relevance gate. True => worth scoring for publication.

    Numeric impact thresholding happens in ``filter_items``; this only weeds
    out items that are categorically out of scope."""
    # Obvious junk is dropped even for speech items.
    if is_ad(item):
        return False
    if is_price_horoscope(item):
        return False
    if is_historical(item):
        return False
    # Upcoming speeches bypass the keyword + opinion gates: a scheduled
    # appearance by a market-moving figure is publishable on its own.
    if is_upcoming_speech(item):
        return True
    if not matches_keywords(item):
        return False
    # Opinions/forecasts only from influential people with a track record.
    if is_opinion(item) and not (item.official or has_influential_author(item)):
        return False
    return True


# === Strict data-quality firewall =========================================
# A deterministic pre-filter that drops historical / commentary / non-news
# content BEFORE any other logic. Strict by design: false positives are
# preferred over letting noise through.

# Any year 2010–2025 (the CURRENT/future year, e.g. 2026, is intentionally
# NOT matched, so genuine current-year news is never flagged historical).
_NOISE_YEAR_RE = re.compile(r"\b20(?:1[0-9]|2[0-5])\b")

# Wording that clearly anchors an item to a current/imminent event.
_CURRENT_FUTURE_RE = re.compile(
    r"\b(?:today|now|breaking|upcoming|will|tonight|this\s+(?:morning|"
    r"afternoon|evening|week)|tomorrow|сегодня|сейчас|завтра)\b",
    re.IGNORECASE,
)

# Commentary / opinion / blog markers (substring, case-insensitive).
_COMMENTARY_NOISE_PHRASES = (
    "according to", "experts say", "analysts say", "some say",
    "believe that", "opinion", "analysis", "op-ed", "blog", "thread",
)

# Retrospective-explanation verbs ("why X happened" content).
_RETRO_EXPLAIN_RE = re.compile(
    r"\b(?:caused|causing|explains?|explained|blamed?|"
    r"here'?s\s+why|reason\s+why|what\s+happened|looking\s+back)\b",
    re.IGNORECASE,
)
# Crypto subjects whose past price post-mortems are noise.
_CRYPTO_SUBJECT_RE = re.compile(
    r"\b(?:bitcoin|btc|ethereum|eth|crypto|altcoin|solana|sol|xrp)\b",
    re.IGNORECASE,
)


def is_invalid_noise(item: NewsItem) -> bool:
    """Strict data-quality firewall. True => drop the item outright.

    Blocks (any one is sufficient):
      A) historical content — a 2010–2025 year with no current/future anchor;
      B) commentary / opinion / blog / analysis phrasing;
      C) retrospective crypto post-mortems ("why BTC crashed", incl. years);
      D) ZeroHedge items with any historical framing.
    Deterministic; runs before everything else in ``filter_items``.
    """
    text = f"{item.title} {item.summary}"
    low = text.lower()
    has_year = bool(_NOISE_YEAR_RE.search(text))
    has_current = bool(_CURRENT_FUTURE_RE.search(text))

    # A) Historical content.
    if has_year and not has_current:
        return True

    # B) Commentary / opinion / blog.
    if any(phrase in low for phrase in _COMMENTARY_NOISE_PHRASES):
        return True

    # C) Retrospective crypto noise: explanation verbs, especially with a year
    #    or a crypto subject; an old year + explanation is always retrospective.
    has_explain = bool(_RETRO_EXPLAIN_RE.search(text))
    if has_explain and (has_year or _CRYPTO_SUBJECT_RE.search(text)):
        return True

    # D) ZeroHedge low-quality retrospectives: any historical framing → drop.
    src = f"{item.source_id} {item.source_name}".lower()
    if "zerohedge" in src and (
        has_year or any(p.search(text) for p in _HISTORICAL_PHRASES)
    ):
        return True

    return False


def filter_items(
    items: Iterable[NewsItem], min_impact: int = DEFAULT_MIN_IMPACT
) -> list[NewsItem]:
    """Apply the relevance gate, refresh impact scores, and DROP anything
    below the publish bar. This is where low-value noise is rejected."""
    kept: list[NewsItem] = []
    for item in items:
        # Strict data-quality firewall — runs BEFORE keyword filtering,
        # speech detection, scoring and AI writing. Non-news / historical /
        # commentary content is dropped here unconditionally.
        if is_invalid_noise(item):
            continue
        if not should_publish(item):
            continue
        item.impact = score_impact(item)
        # Tag upcoming-speech items so the writer renders the ⚠️ pre-event
        # post; they also bypass the tier-2 filler gate below.
        speech = is_upcoming_speech(item)
        item.is_upcoming_speech = speech
        # Tier-2-only catalyst gate: an item whose only relevance is a
        # tier-2 keyword (large-cap equity / commodity / alt-coin / FX)
        # with NO catalyst, NO tier-1 anchor and from no official source
        # is filler ("Gold steady ahead of data", "Visa explores deal").
        # Reject regardless of numeric score. Speeches are exempt.
        if not item.official and not speech:
            text = _text_of(item)
            tier1 = _count_distinct(text, _TIER1_RE, _TIER1_SYM)
            catalysts = _count_distinct(text, _CATALYST_RE, _CATALYST_SYM)
            if tier1 == 0 and catalysts == 0:
                continue
        if item.impact < min_impact and not item.official and not speech:
            continue
        kept.append(item)
    return kept
