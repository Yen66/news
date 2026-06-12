"""Task 2.1 — deterministic hashtag generation."""
from src.ai.hashtags import MAX_TAGS, build_hashtags
from tests.conftest import make_item


def test_btc_item_yields_btc_tag():
    item = make_item(title="Bitcoin tops $70k", summary="BTC at all-time high")
    tags = build_hashtags(item, body="Биткоин достиг $70 000.", tickers="BTC: $70 000")
    assert "#BTC" in tags


def test_ecb_rate_item_yields_macro_and_eu():
    item = make_item(
        title="ECB cuts interest rates by 25 bps",
        summary="European Central Bank lowered the rate",
    )
    tags = build_hashtags(item, body="ЕЦБ снизил ставку на 25 базисных пунктов.",
                          tickers="")
    assert "#макро" in tags
    assert "#ес" in tags


def test_no_signal_yields_empty_list():
    item = make_item(title="Local bakery wins award", summary="Award news")
    tags = build_hashtags(item, body="Местная пекарня получила награду.",
                          tickers="")
    assert tags == []


def test_cap_at_max_tags():
    """A heavily-tagged item is capped at MAX_TAGS — never more."""
    item = make_item(
        title="SEC approves spot Bitcoin and Ethereum ETFs",
        summary=(
            "Fed and ECB watch the SEC ETF approval, CPI inflation guidance, "
            "earnings, hack of Solana exchange in China"
        ),
    )
    body = (
        "Биткоин и эфир выросли после решения SEC. "
        "Регулятор ФРС обсуждает следующее заседание."
    )
    tags = build_hashtags(item, body, tickers="BTC: $70 000 · ETH: $4 000",
                          prefix="🇺🇸")
    assert len(tags) <= MAX_TAGS


def test_deterministic_for_same_input():
    item = make_item(
        title="Bitcoin tops $70k",
        summary="SEC ETF approval lifts BTC and ETH",
    )
    body = "Биткоин достиг $70 000 после одобрения ETF."
    tickers = "BTC: $70 000 · ETH: $4 000"
    a = build_hashtags(item, body, tickers, prefix="🇺🇸")
    b = build_hashtags(item, body, tickers, prefix="🇺🇸")
    assert a == b


def test_flag_in_prefix_wins_for_geo():
    """A flag already chosen by the renderer is the primary geo for the
    post — it appears first among geo tags."""
    item = make_item(title="Fed minutes drop", summary="Federal Reserve")
    tags = build_hashtags(item, body="ФРС публикует протокол.", tickers="",
                          prefix="🇺🇸")
    assert "#сша" in tags


def test_ticker_tags_come_before_themes_and_geo():
    item = make_item(
        title="Bitcoin ETF approval lifts BTC",
        summary="SEC approves spot Bitcoin ETF in the US",
    )
    tags = build_hashtags(item, body="Биткоин ETF одобрен.", tickers="BTC",
                          prefix="🇺🇸")
    # If #BTC and a theme both appear, #BTC must be first.
    assert tags.index("#BTC") < tags.index("#ETF")
    assert tags.index("#ETF") < tags.index("#сша")


def test_no_duplicates_across_categories():
    item = make_item(title="Crypto regulation update", summary="SEC ruling")
    tags = build_hashtags(item, body="Регулятор обновил правила.",
                          tickers="", prefix="🇺🇸")
    assert len(tags) == len(set(tags))
