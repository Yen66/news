"""Strict quality firewall — IF IT IS NOT A REAL CURRENT EVENT, IT MUST NOT
REACH TELEGRAM.

Comprehensive coverage of every content class the firewall guards against
plus every category that must continue to pass.
"""
from src.pipeline import filters
from tests.conftest import make_item


# ============================================================================
# MUST BE DROPPED
# ============================================================================

# --- Historical articles ----------------------------------------------------

HISTORICAL_CASES = [
    "In 2022 Google began meetings with German officials",
    "How Bitcoin survived the 2022 bear market",
    "The 2023 banking crisis revisited",
    "Remember the 2020 crash",
    "Back in 2015 ETH launched at $1",
    "2024 was the year crypto regulation took shape",
]


def test_historical_articles_dropped():
    for title in HISTORICAL_CASES:
        assert filters.is_invalid_noise(make_item(title)), title


# --- Retrospectives ---------------------------------------------------------

RETROSPECTIVE_CASES = [
    "Looking back at the FTX collapse",
    "Year in review: crypto winners and losers",
    "Decade in review: market milestones",
    "Remember when oil hit $150",
    "The rise and fall of LUNA",
    "What happened to ICOs",
    "The story of Mt Gox",
    "This day in history: BTC genesis block",
    "Where are they now: 2017 ICO founders",
    "In retrospect, the 2008 crisis reshaped finance",
]


def test_retrospectives_dropped():
    for title in RETROSPECTIVE_CASES:
        assert filters.is_invalid_noise(make_item(title)), title


# --- Opinion pieces ---------------------------------------------------------

OPINION_CASES = [
    "Bitcoin opinion piece",
    "Op-ed: tariffs hurt growth",
    "In my opinion the Fed is wrong",
    "Our view on inflation",
    "Analysts believe inflation will spike",
    "Experts say AI caused the BTC decline",
    "Experts believe the Fed will pivot",
    "Some say the Fed is behind the curve",
    "Markets moved, according to traders",
    "We believe the trade war will escalate",
    "Editorial: rate cuts are overdue",
]


def test_opinion_pieces_dropped():
    for title in OPINION_CASES:
        assert filters.is_invalid_noise(make_item(title)), title


# --- Analysis articles ------------------------------------------------------

ANALYSIS_CASES = [
    "Deep analysis of the crypto cycle",
    "Commentary on the Fed's pivot",
    "Perspective on the dollar weakness",
    "Bitcoin halving: deep dive",
]


def test_analysis_articles_dropped():
    for title in ANALYSIS_CASES:
        assert filters.is_invalid_noise(make_item(title)), title


# --- Explainers / educational ----------------------------------------------

EXPLAINER_CASES = [
    "Bitcoin halving explained",
    "Tariffs decoded",
    "Beginner's guide to Ethereum",
    "Primer on quantitative tightening",
    "Understanding the Fed's balance sheet",
    "Everything you need to know about CPI",
    "What to know about today's NFP report",
    "Explainer: how spot ETFs work",
    "Stablecoins demystified",
    "Things to watch this week in macro",
]


def test_explainers_dropped():
    for title in EXPLAINER_CASES:
        assert filters.is_invalid_noise(make_item(title)), title


# --- Question-style titles --------------------------------------------------

QUESTION_CASES = [
    "Will Bitcoin reach $200K",
    "What is staking",
    "How to buy Ethereum",
    "Should you sell now",
    "Is the Fed pivoting",
    "Why is inflation high",
    "Could Bitcoin hit a new high",
    "Are we in a recession",
    "When will the Fed cut rates",
    "How does Ethereum staking work",
]


def test_question_titles_dropped():
    for title in QUESTION_CASES:
        assert filters.is_invalid_noise(make_item(title)), title


# --- ZeroHedge extra scrutiny -----------------------------------------------

def test_zerohedge_with_past_year_dropped():
    assert filters.is_invalid_noise(make_item(
        "Remember the 2020 crash",
        source_id="zerohedge", source_name="ZeroHedge"))


def test_zerohedge_without_current_anchor_dropped():
    # Opinion-style headline, no past year, but no "today/now/breaking" hook
    # either — for ZeroHedge that's enough to drop.
    assert filters.is_invalid_noise(make_item(
        "Inflation surges as Fed dithers",
        source_id="zerohedge", source_name="ZeroHedge"))


def test_zerohedge_with_historical_phrase_dropped():
    # "On this day" is a historical phrase regardless of year.
    assert filters.is_invalid_noise(make_item(
        "On this day, markets crashed",
        source_id="zerohedge", source_name="ZeroHedge",
        summary="A look at past events."))


def test_zerohedge_breaking_with_current_anchor_passes():
    # The user wants extra scrutiny on ZH, not a blanket ban.
    assert not filters.is_invalid_noise(make_item(
        "Breaking: Fed cuts rates today",
        source_id="zerohedge", source_name="ZeroHedge"))


# ============================================================================
# MUST PASS (real news the firewall is required to preserve)
# ============================================================================

# --- Upcoming speeches (the user-required explicit bypass) -----------------

SPEECH_PASS_CASES = [
    "Trump to speak today on tariffs",
    "Powell to address Congress on monetary policy",
    "Lagarde is scheduled to speak Tuesday in Frankfurt",
    "Scott Bessent confirmation hearing Wednesday",
    "Lutnick scheduled testimony on China trade",
    "Fed chair will deliver remarks at economic forum tomorrow",
]


def test_upcoming_speeches_pass():
    for title in SPEECH_PASS_CASES:
        assert filters.is_upcoming_speech(make_item(title)), title
        assert not filters.is_invalid_noise(make_item(title)), title


def test_speech_with_old_year_in_topic_still_passes():
    # User requirement #6 + #8: an upcoming speech that happens to reference
    # an old year (e.g. "outlook for 2024 policy") must not be filtered.
    item = make_item(
        "Powell to address Congress on 2024 inflation outlook today")
    assert filters.is_upcoming_speech(item)
    assert not filters.is_invalid_noise(item)


# --- Breaking news ---------------------------------------------------------

BREAKING_CASES = [
    "Breaking: Fed cuts rates 25 bps",
    "Bitcoin surges past 80k now",
    "Tonight: Apple unveils new chip",
    "Just announced: SEC approves spot ETF",
    "Markets rally, S&P 500 hits record today",
    "Just in: Trump signs executive order on tariffs",
]


def test_breaking_news_passes():
    for title in BREAKING_CASES:
        assert not filters.is_invalid_noise(make_item(title)), title


# --- Official announcements ------------------------------------------------

OFFICIAL_CASES = [
    "SEC approves spot bitcoin ETF",
    "Federal Reserve holds rates, signals one cut in 2026",
    "ECB cuts interest rates by 25 bps",
    "Treasury announces new debt auction",
    "BOJ raises rates for first time",
]


def test_official_announcements_pass():
    for title in OFFICIAL_CASES:
        assert not filters.is_invalid_noise(make_item(title, official=True))


# --- Plain factual current-event headlines ---------------------------------

FACTUAL_CASES = [
    "US CPI rises 3.2% in May, hotter than forecast",
    "Tesla shares surge on record deliveries",
    "Nvidia earnings beat estimates",
    "Treasury yields spike to 5%",
    "Coinbase listing expands to 12 countries",
    "Solana network hit by outage, SOL drops",
    "MicroStrategy buys another 10,000 bitcoin",
]


def test_factual_headlines_pass():
    for title in FACTUAL_CASES:
        assert not filters.is_invalid_noise(make_item(title)), title


# --- Current-year news that references an older year (user req #8) --------

def test_current_year_news_referencing_old_year_passes():
    for title in [
        "Today the Fed reversed its 2020 QE policy",
        "Breaking: 2022 crypto crash law goes into effect today",
        "Senate will vote tonight on 2014 banking reform repeal",
    ]:
        assert not filters.is_invalid_noise(make_item(title)), title


# --- Future-year-only mentions (e.g. 2026/2027) survive --------------------

def test_future_year_only_news_passes():
    # The year regex deliberately matches 2010-2025 only, so 2026+ is fine.
    for title in [
        "Federal Reserve holds rates, signals one cut in 2026",
        "Companies prepare for 2027 SEC reporting rules",
    ]:
        assert not filters.is_invalid_noise(make_item(title)), title


# ============================================================================
# INTEGRATION — filter_items runs the firewall FIRST
# ============================================================================

def test_filter_items_drops_noise_before_other_logic():
    items = [
        # Noise — must drop
        make_item("How Bitcoin survived the 2022 bear market"),
        make_item("Experts say AI caused the BTC decline"),
        make_item("Will Bitcoin reach $200K"),
        make_item("Looking back at the FTX collapse"),
        make_item("Bitcoin halving explained"),
        # Real news — must keep
        make_item("Trump to speak today on tariffs"),
        make_item("SEC approves spot bitcoin ETF", official=True),
        make_item("Breaking: Federal Reserve cuts rates 25 bps"),
    ]
    kept_titles = {i.title for i in filters.filter_items(items)}

    # Noise dropped
    for noise in [
        "How Bitcoin survived the 2022 bear market",
        "Experts say AI caused the BTC decline",
        "Will Bitcoin reach $200K",
        "Looking back at the FTX collapse",
        "Bitcoin halving explained",
    ]:
        assert noise not in kept_titles, noise

    # Real news kept
    for real in [
        "Trump to speak today on tariffs",
        "SEC approves spot bitcoin ETF",
        "Breaking: Federal Reserve cuts rates 25 bps",
    ]:
        assert real in kept_titles, real
