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
# 3) Geopolitical scope (Task 1.4)
# ===========================================================================
# Post Task 1.4: geopolitical items publish ONLY if they also carry a market
# anchor. Economic geopolitics (tariffs / OPEC / sanctions / sovereign
# default / debt ceiling / shutdown / elections / export controls) is
# itself a market anchor — those publish unchanged. Pure military/diplomatic
# items without a market anchor (war, ceasefire, military drills, country-
# pair tensions in isolation) are dropped.

# Items that should STILL publish under Task 1.4 (economic-geo, or military
# co-occurring with an oil/index/asset anchor).
GEOPOLITICAL_ACCEPT = [
    "US imposes 50% tariffs on Chinese EVs",            # tariffs (anchor)
    "OPEC+ announces surprise output cut",              # opec (anchor)
    "Russia faces fresh sanctions over energy exports", # sanctions (anchor)
    "Government shutdown looms as debt ceiling talks stall",  # both anchors
    "Sovereign default risk rises for emerging market", # default (anchor)
    "Presidential election: polls tighten in swing states",   # election (anchor)
    "Strait of Hormuz tensions spike oil prices",       # military + oil anchor
    "US announces export controls on advanced chips",   # export controls (anchor)
]


def test_geopolitical_anchored_events_accepted():
    for title in GEOPOLITICAL_ACCEPT:
        item = make_item(title, impact=45)
        assert filters.matches_keywords(item), f"gate dropped: {title}"
        kept = filter_items([item])
        assert kept, f"geopolitical event rejected: {title!r} " \
                     f"(score={score_impact(item)})"


# Pure-military / diplomatic items WITHOUT a market anchor — Task 1.4
# explicitly drops these as off-topic for the crypto+macro channel.
PURE_MILITARY_DROP = [
    "Israel and Iran agree ceasefire after week of strikes",
    "China conducts military drills near Taiwan",
    "Houthis target shipping in the Red Sea",
    "49 Tomahawks fired at Iran nuclear site",
]


def test_pure_military_geopolitics_dropped():
    for title in PURE_MILITARY_DROP:
        item = make_item(title, impact=45)
        kept = filter_items([item])
        assert not kept, (
            f"pure-military item published without market anchor: {title!r}"
        )


def test_anchored_geopolitics_clears_impact_bar():
    # The post-Task-1.4 contract: a geopolitical item with a market anchor
    # scores above DEFAULT_MIN_IMPACT (45) on its own merits.
    geo = make_item("OPEC+ announces surprise output cut spiking oil",
                    impact=45)
    assert score_impact(geo) >= 45


def test_war_does_not_match_warns_or_warning():
    # Word-boundary safety: 'war' must not match inside 'warns' or 'warning'.
    item = make_item("Local bakery warns of rising flour costs", impact=50)
    # Outside our universe; relevance gate rejects it on its own.
    assert not filters.matches_keywords(item)


def test_geopolitical_lifts_score_over_baseline():
    plain = make_item("Quiet market session", impact=50)
    geo = make_item("OPEC+ announces surprise output cut", impact=50)
    assert score_impact(geo) > score_impact(plain)


# Reversibility: the gate can be flipped off via env (or by patching the
# module attr) to restore the prior behavior on short notice.
def test_geopolitics_anchor_gate_is_reversible(monkeypatch):
    monkeypatch.setattr(filters, "GEOPOLITICS_REQUIRES_MARKET_ANCHOR", False)
    item = make_item("Houthis target shipping in the Red Sea", impact=45)
    assert filter_items([item])
