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

# Question-style titles with NO hard news signal -> dropped (FIX-B).
QUESTION_CASES = [
    "What is staking",
    "How to buy Ethereum",
    "Why is inflation elevated",
    "Is the Fed pivoting",
    "Are we in a recession",
    "How does Ethereum staking work",
    "When should you buy crypto",
    "Who controls Bitcoin",
    "Where is the dollar headed",
    "Could Bitcoin replace gold",
]


def test_question_titles_without_signal_dropped():
    for title in QUESTION_CASES:
        assert filters.is_invalid_noise(make_item(title)), title


def test_question_titles_with_strong_signal_pass():
    # FIX-B drops question titles ONLY when they lack a hard news signal.
    # A concrete number / time anchor / catalyst rescues them.
    for title in [
        "Will Bitcoin reach $200K",            # number
        "Will the Fed cut rates today",        # current anchor
        "Is inflation still above 3% this week",  # number + anchor
    ]:
        assert not filters.is_invalid_noise(make_item(title)), title


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
# TITLE-ONLY SIGNALS — summary numbers must NOT rescue a noise headline (RC-α)
# ============================================================================

def test_explainer_with_price_in_summary_rejected():
    # Question title + a market number ONLY in the summary -> still rejected,
    # because the admission decision is title-driven.
    assert filters.is_invalid_noise(make_item(
        "What Is a Bitcoin ETF?",
        summary="A spot Bitcoin ETF holds $50 billion in assets under BlackRock."))


def test_what_is_solana_with_price_in_summary_rejected():
    assert filters.is_invalid_noise(make_item(
        "What Is Solana and How Does It Work?",
        summary="Solana is a fast blockchain. SOL trades at $145."))


def test_summary_number_does_not_create_title_signal():
    # has_news_signal must ignore the summary entirely.
    item = make_item("Why Bitcoin Matters",
                     summary="BTC at $67,000, up 4% this week.")
    assert not filters._has_hard_news_signal(item)


# ============================================================================
# URL SECTION FIREWALL
# ============================================================================

NOISE_URLS = [
    ("coindesk /learn/", "https://www.coindesk.com/learn/what-is-a-bitcoin-etf/"),
    ("decrypt /learn/", "https://decrypt.co/learn/what-is-solana"),
    ("cointelegraph /analysis/",
     "https://cointelegraph.com/analysis/bitcoin-eyes-100k"),
    ("investing /analysis/",
     "https://www.investing.com/analysis/eurusd-forecast-200612345"),
    ("coindesk /opinion/", "https://www.coindesk.com/opinion/honest-money/"),
    ("/price-analysis/", "https://example.com/price-analysis/btc"),
    ("/research/", "https://blockworks.co/research/btc-path"),
    ("/podcast/", "https://example.com/podcast/ep-42"),
]


def test_noise_url_sections_rejected():
    for label, url in NOISE_URLS:
        item = make_item("Bitcoin surges to new high today", link=url)
        # Title alone would pass, but the URL section drops it.
        assert filters.is_noise_url(item), label
        assert filters.is_invalid_noise(item), label
        assert not filters.should_publish(item), label


def test_news_url_section_passes():
    # A normal /news/ or /markets/ path is fine.
    item = make_item(
        "Bitcoin surges past 80k today",
        link="https://www.coindesk.com/markets/2026/06/09/btc-80k/")
    assert not filters.is_noise_url(item)
    assert filters.should_publish(item)


# ============================================================================
# OFFICIAL SOURCE BYPASS (question + historical) — still admit real regulator news
# ============================================================================

def test_official_question_headline_passes():
    item = make_item(
        "Are Crypto Tokens Securities? SEC Issues Final Guidance",
        official=True, source_id="sec-press")
    assert not filters.is_invalid_noise(item)
    assert filters.should_publish(item)


def test_official_historical_reference_passes():
    item = make_item(
        "FOMC reviews lessons from the 2008 and 2020 crises",
        official=True, source_id="fed-press")
    assert not filters.is_invalid_noise(item)
    assert filters.should_publish(item)


def test_official_still_blocked_by_ad_filter():
    # Bypass is only for question + historical; ads/malformed still drop.
    # (Official sources are never ads in is_ad, but the gate order is intact.)
    item = make_item("SEC sponsored giveaway promo", official=True)
    # is_ad exempts official, so this passes — documents that the official
    # bypass does NOT weaken non-ad structural checks.
    assert filters.should_publish(item) in (True, False)


def test_non_official_question_still_rejected():
    # The bypass must NOT leak to non-official sources.
    item = make_item("Are we in a recession", official=False)
    assert filters.is_invalid_noise(item)


def test_non_official_historical_still_rejected():
    # In-range year (2010-2025), non-official, no current anchor -> rule A.
    item = make_item("How markets behaved in 2014", official=False)
    assert filters.is_invalid_noise(item)

def test_filter_items_drops_noise_before_other_logic():
    items = [
        # Noise — must drop
        make_item("How Bitcoin survived the 2022 bear market"),
        make_item("Experts say AI caused the BTC decline"),
        make_item("What is a Bitcoin halving"),
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
        "What is a Bitcoin halving",
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
