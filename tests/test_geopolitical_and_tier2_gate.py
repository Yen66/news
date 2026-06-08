"""Tests for the catalyst-required-for-tier-2 gate and geopolitical tier."""
from src.pipeline import filters
from src.pipeline.filters import filter_items, score_impact
from tests.conftest import make_item


# ===========================================================================
# 1) Tier-2-only items WITHOUT a catalyst / tier-1 anchor are rejected
# ===========================================================================

TIER2_ONLY_NO_CATALYST_REJECT = [
    "Gold steady ahead of data",
    "Visa explores partnership with regional fintech",
    "Oil little changed in quiet trade",
    "Silver flat as traders await direction",
    "Berkshire mentioned in quarterly filings roundup",
    "Walmart shoppers report longer checkout lines",
]


def test_tier2_only_no_catalyst_rejected():
    for title in TIER2_ONLY_NO_CATALYST_REJECT:
        item = make_item(title, impact=55)
        kept = filter_items([item])
        assert not kept, (
            f"tier-2-only filler passed: {title!r} (score={score_impact(item)})"
        )


# ===========================================================================
# 2) Tier-2 + catalyst is still allowed (no over-rejection)
# ===========================================================================

TIER2_WITH_CATALYST_ACCEPT = [
    # tier2 + clear catalyst -> stays in
    ("Gold surges to record high on Fed bets", 50),
    ("Goldman Sachs beats earnings estimates", 50),
    ("Oil plunges as OPEC announces output hike", 50),
    ("AMD acquires AI chip startup for $5B", 50),
]


def test_tier2_with_catalyst_accepted():
    for title, base in TIER2_WITH_CATALYST_ACCEPT:
        item = make_item(title, impact=base)
        kept = filter_items([item])
        assert kept, f"tier-2 + catalyst rejected: {title!r}"


def test_tier2_only_official_bypasses_gate():
    # Official regulator/central-bank entries are never rejected for lack
    # of a tier-1/catalyst — the source itself is the catalyst.
    item = make_item("Quarterly bond holdings update", official=True, impact=85)
    assert filter_items([item])


# ===========================================================================
# 3) Geopolitical tier — treated as a tier-1 catalyst, scores like a Fed event
# ===========================================================================

GEOPOLITICAL_ACCEPT = [
    "US imposes 50% tariffs on Chinese EVs",
    "OPEC+ announces surprise output cut",
    "Russia faces fresh sanctions over energy exports",
    "Government shutdown looms as debt ceiling talks stall",
    "Israel and Iran agree ceasefire after week of strikes",
    "China conducts military drills near Taiwan",
    "Houthis target shipping in the Red Sea",
    "Sovereign default risk rises for emerging market",
    "Presidential election: polls tighten in swing states",
    "Strait of Hormuz tensions spike oil prices",
    "US announces export controls on advanced chips",
]


def test_geopolitical_events_accepted():
    for title in GEOPOLITICAL_ACCEPT:
        item = make_item(title, impact=45)
        assert filters.matches_keywords(item), f"gate dropped: {title}"
        kept = filter_items([item])
        assert kept, f"geopolitical event rejected: {title!r} " \
                     f"(score={score_impact(item)})"


def test_geopolitical_treated_as_tier1():
    # A pure geopolitical headline must score like a tier-1 event.
    geo = make_item("US imposes new tariffs on Chinese imports", impact=50)
    fed = make_item("Federal Reserve holds interest rates steady", impact=50)
    assert abs(score_impact(geo) - score_impact(fed)) <= 25


def test_war_does_not_match_warns_or_warning():
    # Word-boundary safety: 'war' must not match inside 'warns' or 'warning'.
    item = make_item("Local bakery warns of rising flour costs", impact=50)
    # Outside our universe; relevance gate rejects it on its own.
    assert not filters.matches_keywords(item)


def test_geopolitical_lifts_score_over_baseline():
    plain = make_item("Quiet market session", impact=50)
    geo = make_item("OPEC+ announces surprise output cut", impact=50)
    assert score_impact(geo) > score_impact(plain)
