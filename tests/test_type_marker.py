"""Task 2.2 — deterministic news-type marker."""
from datetime import datetime, timedelta, timezone

from src.ai.writer import (
    PostWriter,
    type_marker,
)
from tests.conftest import FakeAIClient, make_item


def _now():
    return datetime.now(timezone.utc)


# --- type_marker unit checks ----------------------------------------------

def test_regulation_marker_for_sec_ruling():
    item = make_item(title="SEC approves spot bitcoin ETF",
                     summary="The Securities and Exchange Commission ruling")
    assert type_marker(item, body="SEC одобрила ETF.", tickers="") == "🏛"


def test_data_marker_for_cpi_release():
    item = make_item(title="US CPI rises 3.2% in May",
                     summary="Inflation data hotter than forecast")
    assert type_marker(item, body="CPI вырос на 3,2%.", tickers="") == "📊"


def test_large_move_marker_for_ten_percent_pct():
    item = make_item(title="Bitcoin plunges", summary="BTC dropped")
    assert type_marker(item, body="Биткоин упал.",
                       tickers="BTC: $55 000 (↓12,5%)") == "💥"


def test_large_move_marker_for_strong_verb():
    item = make_item(title="Bitcoin record high",
                     summary="BTC reached all-time high")
    assert type_marker(item, body="Биткоин обновил рекорд.",
                       tickers="") == "💥"


def test_plain_item_no_marker():
    item = make_item(title="Coinbase listing update",
                     summary="A small product update")
    assert type_marker(item, body="Coinbase обновил продукт.",
                       tickers="BTC: $70 000 (↑0,5%)") == ""


def test_first_match_wins_regulation_over_data():
    # An item that mentions BOTH a regulator AND quarterly results gets the
    # regulation marker (first in the precedence order).
    item = make_item(
        title="SEC charges firm after quarterly results",
        summary="Earnings report triggered investigation",
    )
    assert type_marker(item, body="Регулятор обвинил фирму.",
                       tickers="") == "🏛"


# --- _render_post integration ---------------------------------------------

async def test_render_prepends_marker_to_flag():
    """Type marker is prepended to the existing flag-or-bolt prefix."""
    fields = (
        "ПРЕФИКС: 🇺🇸\n"
        "ТЕКСТ: SEC одобрила восемь спотовых ETF на Ethereum.\n"
        "ТИКЕРЫ: "
    )
    writer = PostWriter(FakeAIClient(reply=fields), enable_editor=False)
    post = await writer.write(make_item(
        "SEC ETF approval", source_name="Reuters",
        summary="SEC approved 8 spot ETFs on Ethereum",
        link="https://reuters.com/a"))
    # Marker first, then the flag.
    assert post.body.startswith("🏛🇺🇸 ")


async def test_speech_item_still_forces_warning():
    """Task 2.2 must NOT weaken the ⚠️ rule for upcoming speeches."""
    fields = (
        "ПРЕФИКС: ⚡️\n"
        "ТЕКСТ: Сегодня выступит представитель ФРС о ставке.\n"
        "ТИКЕРЫ: "
    )
    writer = PostWriter(FakeAIClient(reply=fields), enable_editor=False)
    item = make_item(
        "Fed speech today",
        source_name="CNBC", link="https://cnbc.com/a",
        summary="Fed official speaks about rates today",
        published=_now(),
        is_upcoming_speech=True,
    )
    post = await writer.write(item)
    # ⚠️ must be present (speech rule); a type marker may precede it.
    assert "⚠️" in post.body
    assert "⚡️" not in post.body


async def test_bolt_still_dropped_when_stale():
    """The 2h ⚡️ recency gate is preserved."""
    fields = (
        "ПРЕФИКС: ⚡️\n"
        "ТЕКСТ: Какое-то событие произошло.\n"
        "ТИКЕРЫ: "
    )
    writer = PostWriter(FakeAIClient(reply=fields), enable_editor=False)
    item = make_item(
        "Plain item", source_name="Blog", link="https://b.io/a",
        summary="Some neutral event without strong signals",
        published=_now() - timedelta(hours=5),  # stale -> no ⚡️
    )
    post = await writer.write(item)
    assert "⚡️" not in post.body
