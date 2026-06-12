"""Task 2.1 — deterministic hashtag line for every post.

Produces the trailing hashtag line shown under the source footer. Three
categories in order: ticker tags (#BTC), theme tags (#регулирование),
geo tags (#сша). Total capped at 4 to avoid clutter. Purely deterministic
— no AI calls, no tokens, no network.

Theme/geo maps live in this module so they are easy to extend; the ticker
map reuses ``_COIN_ALIASES`` from ``src/models.py``.
"""
from __future__ import annotations

import re
from typing import Iterable, List

from ..models import _COIN_ALIASES, NewsItem

MAX_TAGS = 4

# Country-flag emoji (already chosen by ``_clean_prefix``) → geo tag.
_FLAG_TO_TAG = {
    "🇺🇸": "#сша",
    "🇪🇺": "#ес",
    "🇨🇳": "#китай",
    "🇷🇺": "#россия",
}

# Theme tags. Each entry is (tag, keywords). Keywords are case-insensitive;
# alphanumeric keywords match on word boundary, multi-word phrases match as
# substrings. Order in this list controls the order of theme tags in the
# output when several themes co-occur.
_THEME_RULES = (
    ("#регулирование", (
        "sec", "регулятор", "регулирован", "regulator", "закон", "law",
        "ruling", "court", "lawsuit", "settlement", "fined", "fine",
        "sanction", "sanctions", "clarity act", "mica",
    )),
    ("#ETF", ("etf",)),
    ("#отчётность", (
        "earnings", "выручка", "results", "guidance", "quarterly",
        "квартал", "прибыль", "отчёт", "отчет",
    )),
    ("#макро", (
        "cpi", "ppi", "pce", "inflation", "инфляц", "rate", "rates",
        "ставк", "fed", "fomc", "ecb", "boj", "pboc", "powell", "lagarde",
        "nfp", "nonfarm", "payrolls", "gdp", "ввп", "interest rate",
        "monetary policy",
    )),
    ("#IPO", ("ipo", "листинг", "listing")),
    ("#безопасность", (
        "hack", "hacked", "exploit", "exploited", "breach", "взлом", "drain",
        "drained",
    )),
)

# Geo tags. Same matching rules as themes. Order matters when multiple
# countries are mentioned in the same item.
_GEO_RULES = (
    ("#сша", (
        "united states", "u.s.", "сша", "america", "американ",
        "fed", "federal reserve", "sec", "trump", "biden", "powell",
    )),
    ("#ес", (
        "european union", "europe", "european", "евросою",
        "ecb", "евроцентр", "lagarde",
    )),
    ("#китай", ("china", "chinese", "китай", "pboc")),
    ("#россия", ("russia", "russian", "россия", "россий")),
)


def _has_keyword(haystack: str, keyword: str) -> bool:
    """Case-insensitive match. Single alphanumeric words match on word
    boundary; anything with whitespace or punctuation matches as substring."""
    if re.fullmatch(r"[a-zа-яё0-9]+", keyword):
        return bool(re.search(rf"\b{re.escape(keyword)}\b", haystack))
    return keyword in haystack


def _ticker_tags(item: NewsItem, body: str, tickers: str) -> List[str]:
    """Asset / ticker hashtags, sourced from _COIN_ALIASES."""
    haystack = f"{item.title} {item.summary} {body} {tickers}".lower()
    # Preserve insertion order: walk aliases by alphabetical key for
    # determinism, dedupe via dict (stable insertion since Py3.7).
    out: dict[str, None] = {}
    for word, canonical in sorted(_COIN_ALIASES.items()):
        if not canonical:
            continue
        if re.search(rf"\b{re.escape(word)}\b", haystack):
            out[f"#{canonical.upper()}"] = None
    return list(out)


def _theme_tags(haystack: str) -> List[str]:
    out: List[str] = []
    for tag, keywords in _THEME_RULES:
        if any(_has_keyword(haystack, kw) for kw in keywords):
            out.append(tag)
    return out


def _geo_tags(haystack: str, prefix: str) -> List[str]:
    out: List[str] = []
    # If the prefix already carries a country flag, that flag wins as the
    # primary geography for the post (the model has already classified it).
    flag_match = re.search(r"[\U0001F1E6-\U0001F1FF]{2}", prefix or "")
    if flag_match:
        tag = _FLAG_TO_TAG.get(flag_match.group(0))
        if tag:
            out.append(tag)
    for tag, keywords in _GEO_RULES:
        if tag in out:
            continue
        if any(_has_keyword(haystack, kw) for kw in keywords):
            out.append(tag)
    return out


def build_hashtags(
    item: NewsItem,
    body: str,
    tickers: str,
    prefix: str = "",
) -> List[str]:
    """Return the post's hashtag line as a list of tags.

    Order: ticker tags first, then theme tags, then geo tags. Duplicates
    removed (a tag never repeats across categories). Capped at MAX_TAGS to
    avoid clutter. An item with no matchable signal returns ``[]`` — the
    renderer then omits the trailing line entirely.
    """
    haystack = f"{item.title} {item.summary} {body} {tickers}".lower()
    ordered: dict[str, None] = {}
    for tag in _ticker_tags(item, body, tickers):
        ordered.setdefault(tag, None)
    for tag in _theme_tags(haystack):
        ordered.setdefault(tag, None)
    for tag in _geo_tags(haystack, prefix):
        ordered.setdefault(tag, None)
    return list(ordered)[:MAX_TAGS]
