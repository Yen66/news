from src.ai.writer import (
    _clean_made_up_names,
    _filter_quote,
    _validate_numbers,
)
from tests.conftest import make_item


def test_clean_made_up_names_hallucinated():
    item = make_item(title="Real news", summary="No such name")
    body = "Джейсон Шен (CEO SpaceX): revenue up"
    result = _clean_made_up_names(body, item)
    assert "представитель компании" in result
    assert "Джейсон" not in result


def test_clean_made_up_names_real():
    item = make_item(title="Elon Musk", summary="Elon Musk said")
    body = "Elon Musk: hello"
    result = _clean_made_up_names(body, item)
    assert "Elon Musk:" in result


def test_filter_quote_generic():
    item = make_item(title="Any", summary="")
    body = 'CEO: «Мы рады результатам»'
    result = _filter_quote(body, item)
    assert '«' not in result
    assert 'рады' not in result


def test_filter_quote_meaningful():
    item = make_item(title="Bitcoin", summary="")
    body = 'Аналитик: «Биткоин достиг $70 000»'
    result = _filter_quote(body, item)
    assert 'Биткоин' in result


def test_validate_numbers_fake():
    item = make_item(title="Oil prices", summary="Oil is up")
    body = "Цена достигла $100 за баррель"
    result = _validate_numbers(body, item)
    assert '[сумма не указана]' in result


def test_validate_numbers_real():
    item = make_item(title="Oil at $95", summary="Crude rose to $95.0")
    body = "Нефть торговалась по $95"
    result = _validate_numbers(body, item)
    assert '$95' in result
