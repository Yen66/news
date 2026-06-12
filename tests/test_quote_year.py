"""Task 1.3 — kill fabricated quotes & wrong years."""
from datetime import datetime, timezone

from src.ai.writer import (
    _filter_quote,
    _strip_invalid_years,
)
from tests.conftest import make_item


# --- _filter_quote: grounding rule ----------------------------------------

def test_filter_quote_invented_dropped_by_grounding():
    """A quote whose significant words are absent from the source is
    fabrication — drop it."""
    item = make_item(
        title="Coinbase wins SEC court ruling",
        summary="Coinbase wins court battle against SEC over staking",
    )
    body = 'Аналитик: «Биткоин завтра упадёт до нуля и забудут о крипте»'
    out = _filter_quote(body, item)
    assert 'Биткоин' not in out
    assert '«' not in out


def test_filter_quote_grounded_in_summary_kept():
    """A quote whose words appear in the source is real reporting — keep."""
    item = make_item(
        title="Биткоин достиг $70 000",
        summary="Bitcoin reached $70 000 milestone today",
    )
    body = 'Аналитик: «Биткоин достиг $70 000»'
    out = _filter_quote(body, item)
    assert 'Биткоин достиг' in out


def test_filter_quote_short_still_dropped():
    """Existing rule: a too-short quote is dropped regardless of grounding."""
    item = make_item(title="Bitcoin update", summary="BTC at $70 000")
    body = 'CEO: «всё хорошо»'  # 10 chars, too short
    out = _filter_quote(body, item)
    assert 'хорошо' not in out


def test_filter_quote_generic_filler_still_dropped():
    """Existing stop-word rule preserved by Task 1.3."""
    item = make_item(title="Earnings call", summary="Acme reported earnings")
    body = 'CEO: «Мы рады результатам и интересным возможностям»'
    out = _filter_quote(body, item)
    assert 'рады' not in out


# --- _strip_invalid_years --------------------------------------------------

def test_strip_invented_past_year_drops_sentence():
    item = make_item(
        title="Bitcoin update", summary="Bitcoin rallied today",
    )
    body = "В 2024 году рынок упал. Сегодня BTC растёт на 5%."
    out = _strip_invalid_years(body, item)
    assert "2024" not in out
    assert "Сегодня BTC растёт" in out


def test_strip_keeps_source_present_year():
    item = make_item(
        title="Crisis lessons since 2020",
        summary="Markets recovered from the 2020 crash",
    )
    body = "Уровни поддержки вернулись к значениям 2020 года."
    out = _strip_invalid_years(body, item)
    assert "2020" in out


def test_strip_keeps_current_year():
    cy = str(datetime.now(timezone.utc).year)
    item = make_item(title="x", summary="y")
    body = f"В {cy} году рынок вырос. Текст продолжается."
    out = _strip_invalid_years(body, item)
    assert cy in out


def test_strip_keeps_future_year_unconditionally():
    item = make_item(title="x", summary="y")
    body = "Решение вступит в силу в 2030 году."
    out = _strip_invalid_years(body, item)
    assert "2030" in out
