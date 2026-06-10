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

# === EVENT-FIRST PUBLISHING (Phase 1) =====================================
# A news channel publishes EVENTS. ``EVENT_TERMS`` are concrete, completed (or
# officially scheduled) ACTIONS — something HAPPENED. These are the positive
# admission signal: an item with no event term, no price move on a tier-1
# subject, no geopolitical catalyst, and no official/influential backing is
# topic / analysis / forecast filler, not news.
#
# Deliberately ACTION VERBS, not outcome nouns: "announces partnership" is an
# event, a bare "partnership" headline ("Visa explores partnership") is not —
# the verb is what makes it news.
EVENT_TERMS = {
    # corporate / product / market structure
    "announces", "announced", "announce", "unveils", "unveiled", "unveil",
    "launches", "launched", "launch", "introduces", "introduced", "debuts",
    "debuted", "rolls out", "rolled out", "releases", "released",
    "lists", "listed", "listing", "delists", "delisted", "relists",
    "acquires", "acquired", "acquisition", "merges", "merged", "merger",
    "buys", "bought", "purchases", "purchased", "sells", "sold", "stake",
    "partners", "partnered",
    "raises", "raised", "secures", "secured", "closes round", "funding round",
    "ipo", "spinoff", "spin-off", "delivers", "delivered",
    # earnings / guidance
    "reports", "reported", "posts", "posted", "earnings", "guidance",
    "beats", "beat", "misses", "missed", "results",
    # regulators / law / courts
    "approves", "approved", "approval", "rejects", "rejected", "rejection",
    "files", "filed", "filing", "sues", "sued", "lawsuit", "charges",
    "charged", "settles", "settled", "settlement", "fines", "fined",
    "rules", "ruled", "ruling", "verdict", "indicts", "indicted",
    "passes", "passed", "enacts", "enacted", "signs", "signed", "ratifies",
    "ratified", "vetoes", "vetoed", "bans", "banned", "halts", "halted",
    "suspends", "suspended", "freezes", "froze", "frozen", "seizes", "seized",
    "imposes", "imposed", "investigates", "investigated", "probe",
    "issues", "issued", "orders", "ordered", "mandates", "warns",
    # central banks / macro releases
    "hikes", "hiked", "cuts", "cut", "raises rates", "holds", "held",
    "decision", "statement", "minutes", "release", "released",
    # incidents
    "hack", "hacked", "hacks", "breach", "breached", "exploit", "exploited",
    "drained", "outage", "halt", "default", "defaults", "defaulted",
    "bankruptcy", "liquidation", "liquidated", "recall", "recalls",
    "layoffs", "lays off", "resigns", "resigned", "steps down", "appoints",
    "appointed", "names", "named", "fires", "fired", "ousts",
    # upgrades / launches / records
    "upgrade", "upgraded", "goes live", "went live", "mainnet", "activates",
    "activated", "record", "all-time high", "milestone",
    "confirms", "confirmed", "wins", "won",
    # milestone / level-reaching (a current event, not a forecast — the
    # forecast gate runs first and catches "could hit / may reach")
    "hits", "hit", "reaches", "reached", "reach", "tops", "topped",
    "touches", "touched", "crosses", "crossed", "breaches", "breached",
    "surpasses", "surpassed", "returns", "returned", "recovers", "recovered",
    "rebounds", "rebounded", "extends", "hovers",
    # geopolitical action verbs
    "ceasefire", "invades", "invaded", "strikes", "struck", "agrees",
    "agreed", "withdraws", "withdrew", "deploys", "deployed",
}

# Price-action verbs. A MOVE is an event ONLY when the subject is a tier-1
# market mover (BTC/ETH, an index, a mega-cap, a macro series). A bare move on
# an obscure or meme asset is a recap, not news.
MOVE_TERMS = {
    "surges", "surge", "surged", "soars", "soar", "soared", "plunges",
    "plunge", "plunged", "tumbles", "tumble", "tumbled", "crashes", "crash",
    "crashed", "spikes", "spike", "spiked", "rallies", "rally", "rallied",
    "jumps", "jump", "jumped", "drops", "drop", "dropped", "falls", "fall",
    "fell", "rises", "rise", "rose", "slides", "slide", "slid", "slips",
    "slip", "slipped", "climbs", "climb", "climbed", "gains", "gain",
    "gained", "sheds", "shed", "sinks", "sink", "sank", "tanks", "tank",
    "tanked", "rockets", "rocket", "rocketed", "dips", "dip", "dipped",
    "spirals", "craters", "slumps", "slump", "dives", "dive", "pops",
}

# Memecoins / pump-driven assets. Price action on these is NOT news; they need
# a real event (listing, hack, lawsuit, major launch) to publish (Phase 7).
MEMECOIN_TERMS = {
    "dogecoin", "doge", "shiba", "shib", "shiba inu", "pepe", "bonk", "floki",
    "dogwifhat", "wif", "meme coin", "memecoin", "mog", "brett", "popcat",
    "bome", "book of meme", "siren", "buildon", "baby doge", "turbo",
    "mother", "daddy", "fartcoin", "neiro",
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
    # Index-name closing-wrap: "S&P 500 closes mixed", "Nasdaq ends higher",
    # "Dow finishes flat". Same shape as the stocks-end-mixed pattern, but
    # matches the major index keywords explicitly (the bare "S&P 500" hits
    # the tier-1 boost so it cleared the impact floor without this guard).
    re.compile(
        r"\b(?:s&p\s*500|sp\s*500|s&p500|nasdaq|dow|dow\s+jones|"
        r"ftse|dax|nikkei|hang\s+seng|stoxx|cac)\s+"
        r"(?:end[s]?|ended|close[ds]?|closed|finish(?:e[ds])?)\s+"
        r"(?:mixed|flat|higher|lower|up|down)\b",
        re.I,
    ),
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
_EVENT_RE, _EVENT_SYM = _build_keyword_matcher(EVENT_TERMS)
_MOVE_RE_KW, _MOVE_SYM = _build_keyword_matcher(MOVE_TERMS)
_GEO_RE, _GEO_SYM = _build_keyword_matcher(GEOPOLITICAL_TERMS)
_MEME_RE, _MEME_SYM = _build_keyword_matcher(MEMECOIN_TERMS)
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

# A year used as a COMPARISON REFERENCE ("since 2021", "last seen in 2020",
# "highest since 2022") anchors a CURRENT event — the year is a benchmark, not
# the topic. These must PASS (Phase 3 false-positive fix).
_YEAR_REFERENCE_RE = re.compile(
    r"\b(?:since|"
    r"last\s+seen\s+(?:in|since)|not\s+seen\s+since|seen\s+since|"
    r"compared\s+(?:to|with)|versus|vs\.?|"
    r"(?:high|low|highest|lowest|strongest|weakest|best|worst|most|peak)"
    r"[^.]{0,20}?\bsince)\s+(?:\w+\s+){0,3}?20[0-9]{2}\b",
    re.I,
)

# Phrasing that makes a PAST YEAR the TOPIC of the article (retrospective):
# the title opens with a year, "YYYY was/became/changed", "lessons from",
# "the YYYY bull market", "why YYYY", "YYYY cycle", etc. These must FAIL.
_RETRO_TOPIC_RE = re.compile(
    r"^\s*20(?:1[0-9]|2[0-5])\b"                       # title opens with a past year
    r"|\b20(?:1[0-9]|2[0-5])\s+(?:was|were|saw|marked|became|brought|"
    r"will\s+be\s+remembered|changed|turned|defined|reshaped)\b"
    r"|\bwhy\s+20(?:1[0-9]|2[0-5])\b"
    r"|\blessons?\s+(?:from|of)\b"
    r"|\bthe\s+20(?:1[0-9]|2[0-5])\s+(?:bull|bear|crash|collapse|cycle|rally|"
    r"crisis|boom|mania|meltdown|run)\b"
    r"|\b20(?:1[0-9]|2[0-5])\s+(?:bull\s+market|bear\s+market|cycle|crash|"
    r"collapse|retrospective|mania|boom|meltdown)\b"
    r"|\b(?:cycle|market|crash|collapse)\s+(?:lessons|retrospective)\b",
    re.I,
)


def _current_year() -> int:
    return datetime.now(timezone.utc).year


def is_year_reference(item: NewsItem) -> bool:
    """True if every past-year mention is a comparison reference (since/last
    seen in), i.e. the year anchors a current event rather than being the
    topic."""
    text = f"{item.title} {item.summary}"
    return bool(_YEAR_REFERENCE_RE.search(text))


def is_retrospective_topic(item: NewsItem) -> bool:
    """True if the article is structurally ABOUT a past year/era.

    A comparison reference ("last seen in 2020", "highest since 2021") is a
    benchmark for a current event, NOT a retrospective topic — so an
    incidental "in 2020" inside such a phrase does not flag it.
    """
    text = f"{item.title} {item.summary}"
    if _RETRO_TOPIC_RE.search(text):
        return True
    if _YEAR_REFERENCE_RE.search(text):
        return False
    return any(p.search(text) for p in _HISTORICAL_PHRASES)


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

    Phase-3 redesign — distinguish ARTICLE-ABOUT-THE-PAST from CURRENT-EVENT-
    WITH-HISTORICAL-REFERENCE:

    1. Retrospective-topic phrasing ("2016 was…", "lessons from the 2021 bull
       market", "why 2022 changed crypto") => historical, unconditionally.
    2. Otherwise, a past year used as a COMPARISON REFERENCE ("falls to levels
       last seen in 2020", "highest since 2021") anchors a CURRENT event =>
       NOT historical.
    3. Fallback: a title made only of past years, OR a body retrospective
       phrase with no current/last-year anchor.
    """
    text = f"{item.title} {item.summary}"
    # 1) Explicit retrospective topic always wins.
    if _RETRO_TOPIC_RE.search(text):
        return True
    # 2) Comparison-reference rescue: the year is a benchmark for a current
    #    event, not the subject.
    if _YEAR_REFERENCE_RE.search(text):
        return False
    # 3) Original heuristics.
    if title_is_historical(item):
        return True
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


# === Event detection (Phase 1) ============================================
def has_real_event(item: NewsItem) -> bool:
    """True if the TITLE describes a real, current event (Phase 1).

    Event-first publishing: an item must carry a concrete action, an official
    backing, a named principal, a geopolitical catalyst, or a price move on a
    tier-1 subject. Title-only by design (RC-α): RSS summaries always carry a
    stray number/verb, so admission must be driven by the headline.
    """
    if item.official or is_upcoming_speech(item):
        return True
    # A named market-moving principal (Powell/Musk/SEC chair/...) makes even a
    # terse headline newsworthy.
    if has_influential_author(item):
        return True
    title = (item.title or "").lower()
    # Geopolitical catalysts are events in their own right (shutdown looms,
    # ceasefire, sanctions, election) even without a separate action verb.
    if _matches(title, _GEO_RE, _GEO_SYM):
        return True
    # An explicit event/action verb.
    if _matches(title, _EVENT_RE, _EVENT_SYM):
        return True
    # A price move counts as an event ONLY for a tier-1 market mover.
    if _matches(title, _MOVE_RE_KW, _MOVE_SYM) and _matches(
        title, _TIER1_RE, _TIER1_SYM
    ):
        return True
    return False


# === Forecast / price-target rejection (Phase 4) ==========================
# Modal speculation pointed at a price move: "could reach", "may surge",
# "will hit $200k", "expected to rally".
_FORECAST_MODAL_MOVE_RE = re.compile(
    r"\b(?:could|would|will|may|might|set\s+to|poised\s+to|expected\s+to|"
    r"on\s+track\s+to|on\s+pace\s+to|likely\s+to|projected\s+to)\s+"
    r"(?:\w+\s+){0,2}?"
    r"(?:reach|hit|rise|rally|surge|soar|climb|jump|top|tops|test|retest|"
    r"revisit|return|rebound|recover|fall|drop|crash|plunge|sink|tumble|"
    r"slide|dip|double|triple|moon|explode|breakout|break|reclaim)\b",
    re.I,
)
# "Analysts expect / strategists predict / traders eye ..."
_FORECAST_ANALYST_RE = re.compile(
    r"\b(?:analysts?|strategists?|traders?|experts?|economists?|"
    r"researchers?|bulls?|bears?)\b[^.]{0,40}?\b"
    r"(?:expect|expects|predict|predicts|forecasts?|see|sees|eye|eyes|"
    r"target|targets|project|projects|anticipate|anticipates|brace)\b",
    re.I,
)
# Analyst price targets.
_PRICE_TARGET_RE = re.compile(
    r"\bprice\s+target\b|\btarget\s+price\b|"
    r"\b(?:raises?|raised|cuts?|cut|lifts?|lifted|lowers?|lowered|trims?|"
    r"trimmed|sets?|set|boosts?|boosted|hikes?|slashes?)\s+"
    r"(?:\w+\s+){0,3}?(?:price\s+)?target\b|"
    r"\bpt\s+(?:raised|cut|lifted|to)\b",
    re.I,
)
# Forecast / opinion topic labels.
_FORECAST_TOPIC_RE = re.compile(
    r"\b(?:outlook|forecast|prediction|predictions|thesis|investment\s+case|"
    r"bull\s+case|bear\s+case|price\s+prediction|year\s+ahead\s+outlook)\b",
    re.I,
)
# "hotter than forecast", "beat forecast", "in line with forecast" — these are
# FACTUAL release reporting, NOT a forecast article.
_FORECAST_FACTUAL_CONTEXT_RE = re.compile(
    r"\b(?:than|vs\.?|versus|above|below|beat|beats|beating|topped?|tops|"
    r"miss(?:ed|es)?|hotter|cooler|stronger|weaker|softer|in\s+line\s+with|"
    r"matched?|exceeded?)\s+(?:\w+\s+){0,3}?forecast",
    re.I,
)


def is_forecast(item: NewsItem) -> bool:
    """True if the item is primarily a forecast / prediction / price target."""
    title = item.title or ""
    if _FORECAST_MODAL_MOVE_RE.search(title):
        return True
    if _FORECAST_ANALYST_RE.search(title):
        return True
    if _PRICE_TARGET_RE.search(title):
        return True
    if _FORECAST_TOPIC_RE.search(title):
        # "3.2%, hotter than forecast" is a factual print, not a forecast.
        if _FORECAST_FACTUAL_CONTEXT_RE.search(title):
            return False
        return True
    return False


# === Technical-analysis rejection (Phase 5) ===============================
# Unambiguous TA indicators / chart patterns.
_TA_STRONG_RE = re.compile(
    r"\b(?:rsi|macd|fibonacci|fib\s+retracement|retracement|golden\s+cross|"
    r"death\s+cross|double\s+top|double\s+bottom|head\s+and\s+shoulders|"
    r"bollinger|moving\s+average|trend\s*line|chart\s+pattern|breakout|"
    r"breakdown|overbought|oversold|ascending\s+triangle|descending\s+triangle|"
    r"falling\s+wedge|rising\s+wedge|bull\s+flag|bear\s+flag|pennant|"
    r"elliott\s+wave|candle(?:stick)?\s+pattern|cup\s+and\s+handle|"
    r"(?:50|100|200)[- ]?day\s+(?:ma|moving\s+average)|ema\b|sma\b)\b",
    re.I,
)
# Support / resistance / price-level framing (kept title-scoped to limit FPs:
# "SEC support for X" must not trip it).
_TA_LEVEL_RE = re.compile(
    r"\b(?:support|resistance)\s+(?:level|zone|line|area|band)\b|"
    r"\b(?:key|major|critical|strong)\s+(?:support|resistance)\b|"
    r"\b(?:support|resistance)\b[^.]{0,15}?\$?\d[\d.,]*\s*[kK%]?\b|"
    r"\bprice\s+level(?:s)?\b|\bkey\s+level(?:s)?\b",
    re.I,
)


def is_technical_analysis(item: NewsItem) -> bool:
    """True if the item is primarily chart / technical analysis (Phase 5)."""
    title = item.title or ""
    if _TA_STRONG_RE.search(title):
        return True
    if _TA_LEVEL_RE.search(title):
        return True
    return False


def is_non_news(item: NewsItem) -> bool:
    """Phase 2 umbrella: the item's primary purpose is NOT a news event —
    it is a forecast, price target, or technical/chart analysis. Other
    non-news classes (opinion/analysis/explainer/retrospective phrasing,
    market wraps, URL sections) are handled by ``is_invalid_noise`` and the
    routine-recap gate."""
    return is_forecast(item) or is_technical_analysis(item)


def is_memecoin_pump(item: NewsItem) -> bool:
    """True if the item is a memecoin price-action story with no real event
    (Phase 7). Memecoins need a listing / hack / lawsuit / major launch."""
    title = (item.title or "").lower()
    if not _matches(title, _MEME_RE, _MEME_SYM):
        return False
    # A genuine event (listing, hack, charges, launch) makes it news.
    if _matches(title, _EVENT_RE, _EVENT_SYM):
        return False
    return True


def should_publish(item: NewsItem) -> bool:
    """The categorical relevance gate. True => worth scoring for publication.

    Numeric impact thresholding happens in ``filter_items``; this only weeds
    out items that are categorically out of scope."""
    # FIX-D: the data-quality firewall is the FIRST gate, so every caller of
    # should_publish (incl. /test-post) inherits it — it is no longer only
    # reachable through filter_items.
    if is_invalid_noise(item):
        return False
    # Obvious junk is dropped even for speech items.
    if is_ad(item):
        return False
    if is_price_horoscope(item):
        return False
    # Historical-year rejection is skipped for official sources (a regulator
    # release may legitimately reference an old year).
    if not item.official and is_historical(item):
        return False
    # Upcoming speeches bypass the keyword + opinion gates: a scheduled
    # appearance by a market-moving figure is publishable on its own.
    if is_upcoming_speech(item):
        return True
    # Phase 2/4/5: HARD rejection of non-news content (forecast / price target
    # / technical analysis) regardless of score. Exempt official sources and
    # named principals (a regulator/Powell "outlook" is still news).
    if (not item.official and not has_influential_author(item)
            and is_non_news(item)):
        return False
    # Phase 7: memecoin price-action with no real event is not news.
    if not item.official and is_memecoin_pump(item):
        return False
    if not matches_keywords(item):
        return False
    # Opinions/forecasts only from influential people with a track record.
    if is_opinion(item) and not (item.official or has_influential_author(item)):
        return False
    # Phase 1 — EVENT-FIRST floor. Replaces the old has_news_signal allow-by-
    # number rule: a non-official item must describe a REAL EVENT (action verb,
    # geopolitical catalyst, named principal, or a price move on a tier-1
    # subject). A bare number / topic keyword is no longer enough.
    if not item.official and not has_real_event(item):
        return False
    return True


# === Strict data-quality firewall =========================================
# A deterministic pre-filter that drops historical / retrospective / opinion
# / commentary / explainer / non-news content BEFORE any other logic
# (keyword gate, scoring, AI writing). Strict by design: false positives
# are preferred over letting noise through.
#
# The ONLY built-in exception is genuine upcoming-speech announcements
# (Trump/Powell/Lagarde/...). Those bypass the firewall at the very top so
# the user-required "warn before market-moving appearances" path stays open.

# Years considered "past" for the historical-content gate. Built dynamically
# from the current year so the regex never goes stale at year boundaries:
# the upper bound is ``current_year - 1`` so 2026/2027 etc. are NEVER flagged
# historical (they're current or future). Cached per year.
_NOISE_YEAR_CACHE: dict[int, re.Pattern] = {}


def _noise_year_re() -> re.Pattern:
    """Regex matching past years (2010 .. current_year-1), refreshed yearly."""
    year = _current_year()
    cached = _NOISE_YEAR_CACHE.get(year)
    if cached is not None:
        return cached
    upper = year - 1
    if upper < 2010:
        # Defensive: clock skew / off-year fallback.
        pattern = re.compile(r"(?!x)x")  # never matches
    else:
        years = "|".join(str(y) for y in range(2010, upper + 1))
        pattern = re.compile(rf"\b(?:{years})\b")
    _NOISE_YEAR_CACHE[year] = pattern
    return pattern

# Wording that clearly anchors an item to a current/imminent event.
_CURRENT_FUTURE_RE = re.compile(
    r"\b(?:today|now|breaking|just\s+(?:announced|in|hit|crossed|posted)|"
    r"upcoming|tonight|tomorrow|this\s+(?:morning|afternoon|evening|week)|"
    r"will|сегодня|сейчас|завтра)\b",
    re.IGNORECASE,
)

# Commentary / opinion / analysis / explainer / retrospective / non-news
# markers — substring match in title+body, case-insensitive. Deliberately
# broad: each phrase is a strong signal the content is NOT a current event.
_COMMENTARY_NOISE_PHRASES = (
    # --- "According to" sourcing ----------------------------------------
    "according to",
    # --- "X say/believe/think" sourcing-to-opinion frames ---------------
    "experts say", "experts said", "experts believe", "experts think",
    "analysts say", "analysts said", "analysts believe", "analysts think",
    "some say", "some believe", "some think",
    "many say", "many believe", "many think",
    "traders say", "investors say", "sources say",
    "we believe", "we think", "we expect", "we see",
    "they believe", "they think",
    # --- Generic opinion framing ----------------------------------------
    "in my opinion", "in our opinion", "my view", "our view",
    "believe that", "thinks that",
    # --- Opinion / analysis labels --------------------------------------
    "opinion", "op-ed", "analysis", "commentary", "perspective",
    "editorial",
    # --- Non-news format markers ----------------------------------------
    "blog", "thread", "podcast", "newsletter", "deep dive",
    # --- Retrospective / year-independent -------------------------------
    "looking back", "look back", "year in review", "year-in-review",
    "year-end review", "decade in review", "in retrospect", "retrospective",
    "remember when", "remember the",
    "what happened to", "where are they now",
    "the rise and fall", "the story of", "the history of",
    "this day in history", "on this day",
    # --- Explainer / educational / preview-list framing -----------------
    "explainer", "explained", "demystified", "decoded",
    "guide to", "beginner's guide", "beginner guide",
    "primer on", "understanding the",
    "everything you need to know", "all you need to know",
    "what to know about", "things to know about", "things to watch",
    "need to know", "things to know", "the case for",
)

# Structural question/clickbait detection (FIX-B): any title that OPENS with
# an interrogative word is speculation / explainer / clickbait UNLESS it also
# carries a hard news signal. Replaces the old subject-specific list.
_QUESTION_START_RE = re.compile(
    r"^\s*(?:what|why|how|when|where|who|is|are|can|could|would|should|will)\b",
    re.IGNORECASE,
)

# Concrete market-data numbers: currency+digit, digit+%, a magnitude-suffixed
# figure, or a 3+ digit figure (price / level). A bare "5" / "10" does NOT
# qualify, so listicles ("5 things to know") get no numeric signal.
_NEWS_NUMBER_RE = re.compile(
    r"[$€£₽₿]\s?\d"
    r"|\d[\d.,]*\s?%"
    r"|\b\d[\d.,]*\s?(?:k|m|bn|b|tr|trillion|billion|million|thousand|"
    r"млн|млрд|трлн|тыс)\b"
    r"|\b\d{3,}\b",
    re.IGNORECASE,
)


def _has_hard_news_signal(item: NewsItem) -> bool:
    """A 'this is a real current event' signal in the TITLE only.

    TITLE-ONLY by design (RC-α fix): RSS summaries from crypto/markets feeds
    almost always carry a price/%/ticker, which would let any Learn/opinion
    article satisfy the floor. The admission decision must be title-driven;
    the summary is only used later by the AI writer.
    """
    title = item.title or ""
    if _CURRENT_FUTURE_RE.search(title):
        return True
    if _NEWS_NUMBER_RE.search(title):
        return True
    if _count_distinct(title.lower(), _CATALYST_RE, _CATALYST_SYM):
        return True
    return False


def has_news_signal(item: NewsItem) -> bool:
    """Positive-signal floor (FIX-A). True if the TITLE looks like real news.

    Either a hard signal (anchor / number / catalyst) OR a named tier-1
    market-moving institution (SEC/Fed/ECB/Treasury/ETF/exchange/major
    crypto company) — all evaluated on the TITLE ONLY (RC-α fix).
    """
    if _has_hard_news_signal(item):
        return True
    return _matches((item.title or "").lower(), _TIER1_RE, _TIER1_SYM)


# === URL section firewall =================================================
# Deterministic substring blocklist over item.link. Crypto/markets outlets
# encode the section in the URL path (CoinDesk /learn/, Decrypt /learn/,
# CoinTelegraph /analysis/, Investing /analysis/, …). Dropping by section is
# immune to summary contamination. Configurable — extend as feed logs reveal
# new sections. Verify against real "Poll #N sample <src>" link logs.
NOISE_URL_SECTIONS = (
    "/learn/", "/education/", "/academy/", "/guide/", "/guides/",
    "/explainer/", "/explained/", "/analysis/", "/price-analysis/",
    "/opinion/", "/opinions/", "/editorial/", "/commentary/",
    "/research/", "/deep-dive/", "/podcast/", "/newsletter/",
)


def is_noise_url(item: NewsItem) -> bool:
    """True if the article URL is in a non-news section (Learn/Opinion/…)."""
    link = (item.link or "").lower()
    return any(section in link for section in NOISE_URL_SECTIONS)


# Retrospective-explanation verbs ("why X happened / what caused Y" content).
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

    Runs before everything else in ``filter_items``. Blocks (any one is
    sufficient):

      A) historical content — a 2010-2025 year with no current/future anchor;
      B) commentary / opinion / blog / analysis / explainer / retrospective
         phrasing (substring match in title+body);
      C) retrospective crypto post-mortems (explanation verbs + year or
         crypto subject);
      D) question-style titles (speculation / explainer / clickbait);
      E) ZeroHedge items missing a current anchor, carrying a past year,
         or carrying any historical phrase.
      U) URL section (Learn/Opinion/Analysis/…) — non-official only.

    Official sources (SEC/Fed/ECB) are exempt from the question (D),
    historical-year (A) and commentary-phrase (B) rules — a regulator
    headline may legitimately ask a question, cite an old year, or use
    "analysis/opinion/according to" colloquially — but still pass every
    other check. Genuine upcoming-speech announcements bypass relevance
    gates via ``is_upcoming_speech`` so user-required pre-event warnings
    still pass, BUT they cannot bypass the URL-section firewall: a
    ``/learn/`` or ``/analysis/`` URL whose body happens to mention an
    upcoming Powell speech is still a non-news explainer and is dropped.
    """
    official = item.official

    # U) URL section firewall — Learn/Opinion/Analysis/etc. Runs BEFORE the
    #    speech bypass so an explainer URL cannot be rescued by a stray
    #    speech-intent phrase in its body. Skipped for official sources
    #    (regulator URLs never carry these sections, and a rare official
    #    /research/ note should not be silently dropped).
    if not official and is_noise_url(item):
        return True

    # Hard exception: real upcoming speeches always survive (post-URL).
    if is_upcoming_speech(item):
        return False

    title = item.title or ""
    text = f"{title} {item.summary}"
    low_title = title.lower()
    is_reference = is_year_reference(item)

    # Phase 3: an article structurally ABOUT a past year/era (retrospective)
    # is historical noise regardless of any incidental anchor word. The
    # comparison-reference guard keeps "levels last seen in 2020" / "highest
    # since 2021" (current events) from being mis-flagged. Official exempt.
    if not official and not is_reference and is_retrospective_topic(item):
        return True

    has_year = bool(_noise_year_re().search(text))
    # An item is "current-anchored" if it carries a future/imminent phrase, the
    # current year string itself (F11), OR the past year is only a comparison
    # reference ("since 2021", "last seen in 2020") — a current event.
    has_current = (
        bool(_CURRENT_FUTURE_RE.search(text))
        or str(_current_year()) in text
        or is_reference
    )

    # A) Historical content (year reference with no current/future anchor).
    #    Skipped for official sources (a Fed release may cite 2008/2020).
    if not official and has_year and not has_current:
        return True

    # B) Commentary / opinion / analysis / explainer / retrospective phrases.
    #    Title-only check (F1): an "analysis" / "according to" / "we expect"
    #    inside a news body is normal wire-copy phrasing and must NOT block
    #    legitimate breaking news. Officials are exempt — a regulator press
    #    release may use these words descriptively.
    if not official and any(
        phrase in low_title for phrase in _COMMENTARY_NOISE_PHRASES
    ):
        return True

    # C) Retrospective crypto noise.
    if _RETRO_EXPLAIN_RE.search(text) and (
        has_year or _CRYPTO_SUBJECT_RE.search(text)
    ):
        return True

    # D) Question / clickbait titles (structural): opens with an interrogative
    #    word and has no hard news signal -> speculation / explainer. Skipped
    #    for official sources (a regulator may legitimately ask a question).
    if (not official and _QUESTION_START_RE.match(title)
            and not _has_hard_news_signal(item)):
        return True

    # E) ZeroHedge: extra scrutiny. Drop if any of:
    #    - any past year present (per dynamic _noise_year_re),
    #    - no current/imminent anchor at all,
    #    - any historical phrase.
    src = f"{item.source_id} {item.source_name}".lower()
    if "zerohedge" in src:
        if has_year or not has_current:
            return True
        if any(p.search(text) for p in _HISTORICAL_PHRASES):
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
            # Filler: tier-2-only, no catalyst, no tier-1 anchor — AND no real
            # event (a milestone verb like "hits"/"reaches" is an event but
            # not a CATALYST term, so defer to has_real_event to avoid
            # dropping "Gold hits highest since 2020").
            if (tier1 == 0 and catalysts == 0
                    and not has_real_event(item)):
                continue
            # F3: hard reject for routine recap / preview headlines
            # ("Week ahead: …", "Market wrap", "Wall Street recap",
            # "Stocks end mixed") even when they happen to name a tier-1
            # keyword. A genuine event hiding inside a wrap-style headline
            # is rescued by a catalyst verb in the same text.
            wrap_text = f"{item.title} {item.summary}"
            if (
                any(p.search(wrap_text) for p in _ROUTINE_PHRASES)
                and catalysts == 0
            ):
                continue
        if item.impact < min_impact and not item.official and not speech:
            continue
        kept.append(item)
    return kept
