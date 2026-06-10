"""Event-first publishing model (Phases 1, 2, 4, 5, 7).

A NEWS channel publishes EVENTS. Forecasts, analyst opinions, technical
analysis and memecoin price-action are NOT events and must be rejected
regardless of impact score. Real events must still pass.

Cases are drawn from the production-failure audit.
"""
from src.pipeline import filters
from src.pipeline.filters import filter_items
from tests.conftest import make_item


# ===========================================================================
# Phase 1 — has_real_event gate
# ===========================================================================

REAL_EVENTS = [
    "SEC approves spot bitcoin ETF",
    "Coinbase launches new staking service",
    "MicroStrategy buys another 10,000 bitcoin",
    "Federal Reserve cuts rates 25 bps",
    "ECB holds interest rates steady",
    "Nvidia reports record earnings, beats estimates",
    "Binance lists new token",
    "Solana network hit by outage",
    "Circle files for IPO",
    "Coinbase wins court ruling against SEC",
    "OPEC+ announces surprise output cut",
    "US imposes 50% tariffs on Chinese EVs",
    "Bitcoin surges past 80k",            # move on a tier-1 subject
    "Tesla shares plunge after weak deliveries",
]


def test_real_events_have_event_signal():
    for title in REAL_EVENTS:
        assert filters.has_real_event(make_item(title)), title


NON_EVENTS = [
    "Bitcoin price outlook for the second half",
    "Ethereum forecast: what comes next",
    "A deep look at the crypto market structure",
    "Gold steady ahead of data",             # tier-2, no event, no move-on-tier1
    "What staking means for investors",
]


def test_non_events_have_no_event_signal():
    for title in NON_EVENTS:
        assert not filters.has_real_event(make_item(title)), title


# ===========================================================================
# Phase 4 — forecasts / price targets rejected
# ===========================================================================

FORECASTS_REJECT = [
    "Bitcoin will reach $200k",
    "Ethereum could hit $10k",
    "XRP may surge",
    "BTC could rise",
    "ETH may rally",
    "XRP might reach new highs",
    "Analysts expect Bitcoin to rally",
    "Analysts expect gains across crypto",
    "Strategists predict a year-end rally",
    "Price target raised on Coinbase",
    "Analyst sets $250 price target on Nvidia",
    "Goldman raises target price on Tesla",
    "Cuts target on MicroStrategy",
    "Bitcoin outlook turns bullish",
    "Ethereum forecast for 2027",
]


def test_forecasts_rejected():
    for title in FORECASTS_REJECT:
        item = make_item(title)
        assert filters.is_forecast(item), f"not flagged: {title}"
        assert not filters.should_publish(item), f"published: {title}"
        assert not filter_items([item]), f"kept: {title}"


# Real events that LOOK forecast-adjacent but must PASS.
FORECAST_LOOKALIKES_PASS = [
    "BTC falls after CPI release",
    "ETH jumps after ETF approval",
    "Bitcoin rises following SEC decision",
    "US CPI rises 3.2% in May, hotter than forecast",   # factual print
    "Nonfarm payrolls beat forecast, unemployment falls",
]


def test_forecast_lookalikes_pass():
    for title in FORECAST_LOOKALIKES_PASS:
        item = make_item(title)
        assert not filters.is_forecast(item), f"wrongly flagged: {title}"
        assert filters.should_publish(item), f"rejected: {title}"


# ===========================================================================
# Phase 5 — technical analysis rejected (content-based, not URL-based)
# ===========================================================================

TA_REJECT = [
    "Support level at $55k",
    "Resistance level at $68k",
    "BTC eyes support at $55K, resistance at $60K",
    "Golden cross forms on the daily chart",
    "Death cross appears for Ethereum",
    "Double bottom appears on BTC",
    "RSI turns bullish for Bitcoin",
    "MACD crossover signals momentum",
    "Bitcoin tests key resistance",
    "Fibonacci retracement points to $50k",
    "Bitcoin forms a bull flag",
]


def test_technical_analysis_rejected():
    for title in TA_REJECT:
        item = make_item(title)
        assert filters.is_technical_analysis(item), f"not flagged: {title}"
        assert not filters.should_publish(item), f"published: {title}"
        # Crucially this works WITHOUT a /analysis/ URL section.
        assert not filter_items([item]), f"kept: {title}"


def test_ta_does_not_overmatch_real_news():
    # "support" in a non-TA sense must not trip the filter.
    for title in [
        "ECB pledges support for eurozone banks",
        "Congress votes to support stablecoin bill",
        "SEC approves spot bitcoin ETF",
    ]:
        assert not filters.is_technical_analysis(make_item(title)), title


# ===========================================================================
# Phase 7 — memecoin price-action rejected, memecoin events allowed
# ===========================================================================

MEME_PUMPS_REJECT = [
    "Dogecoin surges 30% after Musk post",
    "SHIB jumps 20% in 24 hours",
    "PEPE rockets to new high",
    "BONK pumps as volume spikes",
    "FLOKI rallies 15%",
]


def test_memecoin_pumps_rejected():
    for title in MEME_PUMPS_REJECT:
        item = make_item(title)
        assert filters.is_memecoin_pump(item), f"not flagged: {title}"
        assert not filter_items([item]), f"kept: {title}"


MEME_EVENTS_PASS = [
    "Coinbase lists Dogecoin",
    "SEC charges PEPE promoter with fraud",
    "Binance delists SHIB trading pairs",
]


def test_memecoin_events_pass():
    for title in MEME_EVENTS_PASS:
        item = make_item(title)
        assert not filters.is_memecoin_pump(item), f"wrongly flagged: {title}"
        assert filter_items([item]), f"rejected: {title}"
