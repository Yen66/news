"""Signal-to-noise tests for the redesigned relevance + impact scoring.

The channel serves crypto + macro traders. High-priority crypto/macro/mega-cap
news must pass; regional indexes, generic analyst commentary and catalyst-free
move recaps must be rejected by the MIN_IMPACT_TO_PUBLISH bar.
"""
from src.pipeline import filters
from src.pipeline.filters import DEFAULT_MIN_IMPACT, filter_items, score_impact
from tests.conftest import make_item


# --- HIGH-priority items that MUST still be published ----------------------

ACCEPT_CASES = [
    ("US CPI rises 3.2% in May, hotter than forecast", False, 55),
    ("Federal Reserve holds rates, signals one cut in 2026", False, 60),
    ("ECB cuts interest rates by 25 bps", False, 60),
    ("Bank of Japan raises rates for first time in years", False, 55),
    ("SEC approves spot Ethereum ETF", True, 85),
    ("BlackRock spot bitcoin ETF sees record inflows", False, 55),
    ("Nonfarm payrolls smash expectations, unemployment falls", False, 55),
    ("Nvidia earnings beat estimates, guidance raised", False, 55),
    ("MicroStrategy buys another 10,000 bitcoin", False, 50),
    ("Coinbase wins court ruling against SEC", False, 55),
    ("Treasury yields spike after hot inflation print", False, 55),
    ("Tesla shares surge on record deliveries", False, 55),
    ("Solana network hit by outage, SOL drops", False, 45),
    ("Powell warns inflation may persist, markets watch", False, 40),
]


def test_high_priority_items_pass():
    for title, official, base in ACCEPT_CASES:
        item = make_item(title, official=official, impact=base)
        assert filters.should_publish(item), f"gate rejected: {title}"
        kept = filter_items([item])
        assert kept, f"impact bar rejected: {title} (score={score_impact(item)})"


# --- LOW-priority items that MUST be rejected ------------------------------

REJECT_CASES = [
    # Regional indexes / local markets (no tier-1 anchor).
    ("Jakarta stocks slip 0.4% in quiet trade", False, 45),
    ("Sensex ends marginally lower amid profit booking", False, 45),
    ("Hang Seng falls 0.3% as property names drag", False, 45),
    ("FTSE 100 edges up 0.2% led by miners", False, 45),
    ("Nikkei closes mixed in thin holiday trading", False, 45),
    # Generic analyst commentary, no catalyst.
    ("Analyst says oil could drift lower next quarter", False, 45),
    ("Strategist shares outlook on what to watch this week", False, 40),
    # Routine recaps / merely restating a move.
    ("Markets wrap: stocks end mixed ahead of data", False, 50),
    ("Gold edges down 0.2% as dollar firms", False, 45),
    ("Week ahead: a look at the day ahead in markets", False, 45),
]


def test_low_value_items_rejected():
    for title, official, base in REJECT_CASES:
        item = make_item(title, official=official, impact=base)
        kept = filter_items([item])
        assert not kept, (
            f"low-value item passed: {title} (score={score_impact(item)})"
        )


# --- Scoring mechanics -----------------------------------------------------

def test_tier1_outscores_tier2():
    t1 = make_item("Bitcoin ETF flows hit record", impact=40)
    t2 = make_item("Gold edges higher today", impact=40)
    assert score_impact(t1) > score_impact(t2)


def test_official_central_bank_always_clears_bar():
    item = make_item("Rate decision statement", official=True, impact=85)
    assert filter_items([item])  # official bypasses the numeric bar


def test_regional_penalty_only_without_tier1():
    # Regional index mentioned but the story is really about the Fed -> kept.
    anchored = make_item(
        "Fed decision sends Nikkei and S&P 500 higher",
        impact=55,
    )
    assert score_impact(anchored) >= DEFAULT_MIN_IMPACT
    # Pure regional, no anchor -> penalised below the bar.
    pure = make_item("Nikkei climbs 0.5% on tech buying", impact=55)
    assert score_impact(pure) < DEFAULT_MIN_IMPACT


def test_catalyst_lifts_score():
    plain = make_item("Coinbase listing update", impact=40)
    catalyst = make_item("Coinbase launches new staking product", impact=40)
    assert score_impact(catalyst) >= score_impact(plain)


def test_routine_move_recap_penalised():
    recap = make_item("S&P 500 closes mixed, up 0.1% on the day", impact=50)
    real = make_item("S&P 500 plunges as Fed signals more hikes", impact=50)
    assert score_impact(real) > score_impact(recap)


def test_generic_stocks_keyword_no_longer_qualifies():
    # 'stocks'/'shares' alone (no tier term) must not pass the relevance gate.
    item = make_item("Local shares mixed as investors await earnings season")
    # 'earnings' is tier-2, so this one is relevant; use a purely generic one:
    generic = make_item("Local shares drift in light trading")
    assert not filters.matches_keywords(generic)
    assert filters.matches_keywords(item)  # 'earnings' keeps it in-universe


def test_score_is_clamped():
    item = make_item(
        "SEC approves spot bitcoin ETF as Fed cuts rates; Nvidia surges",
        official=True, impact=90,
    )
    assert 0 <= score_impact(item) <= 100
