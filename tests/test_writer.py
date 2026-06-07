from src.ai.writer import (
    PostWriter,
    credibility_label,
    is_established_source,
    sanitize_text,
    _parse_fields,
    _render_post,
    _strip_forbidden,
)
from tests.conftest import FakeAIClient, make_item

FIELDS = (
    "ЗАГОЛОВОК: Биткоин пробил 100k\n"
    "ТЕКСТ: Биткоин вырос на 5% до 100000 долларов. Приток в ETF составил "
    "1 млрд долларов за день. Спрос со стороны институционалов ускоряется.\n"
    "ВЛИЯНИЕ: высокое ↑ бычье\n"
    "АКТИВЫ: BTC, ETH"
)


async def test_writer_renders_structured_html_post():
    ai = FakeAIClient(reply=FIELDS)
    writer = PostWriter(ai, enable_editor=False)
    item = make_item(
        "Bitcoin hits 100k",
        source_name="CoinDesk",
        link="https://coindesk.com/x",
    )
    post = await writer.write(item)
    b = post.body
    assert "<b>БИТКОИН ПРОБИЛ 100K</b>" in b
    assert "Влияние: высокое ↑ бычье" in b
    assert "Активы: BTC, ETH" in b
    assert '<a href="https://coindesk.com/x">CoinDesk</a>' in b
    assert "◉ Официально" in b
    # No timestamp / MSK / raw "Источник:" footer anymore.
    assert "МСК" not in b
    assert "Время" not in b
    assert "Источник:" not in b


def test_established_sources_are_official():
    assert is_established_source(
        make_item("x", source_name="CoinDesk", link="https://www.coindesk.com/a")
    )
    assert is_established_source(
        make_item("x", source_name="Reuters", link="https://reuters.com/a")
    )
    assert is_established_source(make_item("x", official=True))
    assert is_established_source(
        make_item("x", source_name="SEC", link="https://www.sec.gov/news")
    )


def test_unknown_sources_are_rumor():
    assert not is_established_source(
        make_item("x", source_name="Random Blog", link="https://randomblog.xyz/a")
    )
    assert credibility_label(
        make_item("x", source_name="cryptoguy", link="https://t.me/cryptoguy")
    ) == "◎ Слух"
    assert credibility_label(
        make_item("x", source_name="Bloomberg", link="https://bloomberg.com")
    ) == "◉ Официально"


def test_gov_domain_is_official():
    assert is_established_source(
        make_item("x", source_name="Treasury", link="https://home.treasury.gov/n")
    )


def test_parse_fields_is_lenient():
    f = _parse_fields(
        "заголовок: Тест\nтекст: Раз два три\n"
        "влияние: низкое → нейтральное\nактивы: BTC"
    )
    assert f["ЗАГОЛОВОК"] == "Тест"
    assert f["ТЕКСТ"] == "Раз два три"
    assert f["АКТИВЫ"] == "BTC"


def test_render_fallback_when_fields_missing():
    item = make_item("Fallback Title", source_name="Decrypt", link="https://d.co/a")
    body = _render_post({}, item)
    assert "<b>FALLBACK TITLE</b>" in body  # uppercased headline fallback
    assert "Влияние:" in body
    assert "Активы:" in body


def test_html_is_escaped():
    fields = (
        "ЗАГОЛОВОК: A & B\nТЕКСТ: 5 < 10 > 3 рост\n"
        "ВЛИЯНИЕ: среднее → нейтральное\nАКТИВЫ: BTC"
    )
    body = _render_post(_parse_fields(fields), make_item(
        "x", source_name="A&B", link="https://a.com"))
    assert "&amp;" in body
    assert "&lt;" in body
    assert "&gt;" in body


async def test_editor_runs_for_established_source():
    ai = FakeAIClient(reply=FIELDS)
    writer = PostWriter(ai, enable_editor=True)
    item = make_item("x", source_name="CoinDesk", link="https://coindesk.com/x")
    post = await writer.write(item)
    assert post.editor_used
    assert len(ai.calls) == 2  # writer + editor


async def test_editor_skipped_for_unknown_low_impact():
    ai = FakeAIClient(reply=FIELDS)
    writer = PostWriter(ai, enable_editor=True)
    item = make_item(
        "x", source_name="Random Blog", link="https://blog.xyz/a", impact=30
    )
    post = await writer.write(item)
    assert not post.editor_used
    assert len(ai.calls) == 1


def test_sanitize_strips_cjk_keeps_russian_latin_arrows():
    # The exact bug from the report: Chinese chars inside a Russian word.
    assert sanitize_text("затрагивает主要ые активы") == "затрагиваетые активы"
    # Arrows and tickers must survive.
    assert sanitize_text("высокое ↑ бычье BTC 100000") == (
        "высокое ↑ бычье BTC 100000"
    )
    # Japanese / Korean / emoji-like glyphs removed.
    assert "日本" not in sanitize_text("рынок 日本 растёт")
    assert sanitize_text("цена $100 и €50") == "цена $100 и €50"


def test_render_strips_cjk_from_fields():
    fields = _parse_fields(
        "ЗАГОЛОВОК: Биткоин 主要 растёт\n"
        "ТЕКСТ: Цена выросла на 5%主要 за день.\n"
        "ВЛИЯНИЕ: высокое ↑ бычье\n"
        "АКТИВЫ: BTC"
    )
    body = _render_post(fields, make_item("x", source_name="CoinDesk",
                                          link="https://coindesk.com/a"))
    assert "主要" not in body
    assert "↑ бычье" in body


def test_strip_forbidden_phrases():
    assert "Суть:" not in _strip_forbidden("Суть: Биткоин вырос")
    assert "Оценка:" not in _strip_forbidden("Оценка: высокое")
    assert "не указана" not in _strip_forbidden("Дата не указана сегодня")


async def test_render_removes_forbidden_in_body():
    fields = (
        "ЗАГОЛОВОК: Тест\nТЕКСТ: Суть: Биткоин вырос на 10%.\n"
        "ВЛИЯНИЕ: высокое ↑ бычье\nАКТИВЫ: BTC"
    )
    ai = FakeAIClient(reply=fields)
    writer = PostWriter(ai, enable_editor=False)
    post = await writer.write(make_item("x", source_name="Blog",
                                        link="https://b.io/a"))
    assert "Суть:" not in post.body


async def test_post_official_reflects_source():
    ai = FakeAIClient(reply=FIELDS)
    writer = PostWriter(ai, enable_editor=False)
    official = await writer.write(
        make_item("x", source_name="CNBC", link="https://cnbc.com/a")
    )
    rumor = await writer.write(
        make_item("x", source_name="SomeBlog", link="https://b.io/a")
    )
    assert official.official is True
    assert rumor.official is False
