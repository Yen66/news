from src.ai.writer import (
    PostWriter,
    credibility_label,
    is_established_source,
    sanitize_text,
    _clean_prefix,
    _parse_fields,
    _render_post,
    _strip_forbidden,
    _strip_urls,
)
from tests.conftest import FakeAIClient, make_item

# A full drop with prefix + ticker line.
FIELDS = (
    "ПРЕФИКС: ⚡️\n"
    "ТЕКСТ: Биткоин и эфир потеряли $390 млрд за неделю — худший обвал с "
    "краха FTX. Массовые ликвидации давят на рынок. Следующая поддержка BTC — "
    "$55 000.\n"
    "ТИКЕРЫ: BTC: $59 215 (↓7,25%) · ETH: $2 890 (↓12,3%)"
)


async def test_writer_renders_new_format():
    ai = FakeAIClient(reply=FIELDS)
    writer = PostWriter(ai, enable_editor=False)
    item = make_item(
        "Crypto crash", source_name="CoinDesk", link="https://coindesk.com/x"
    )
    post = await writer.write(item)
    b = post.body
    # No bold ALL-CAPS headline.
    assert "<b>" not in b
    # Body present, starts with the bolt prefix.
    assert b.startswith("⚡️ Биткоин и эфир потеряли $390")
    # Monospace ticker line.
    assert "<code>BTC: $59 215 (↓7,25%) · ETH: $2 890 (↓12,3%)</code>" in b
    # Source line last, clickable name, no visible raw URL text in body.
    assert b.strip().endswith(
        '◉ Официально · <a href="https://coindesk.com/x">CoinDesk</a>'
    )
    # Forbidden leftovers gone.
    for bad in ("МСК", "Время:", "Суть:", "Влияние:", "Активы:", "Метка:"):
        assert bad not in b


async def test_no_ticker_line_when_absent():
    fields = (
        "ПРЕФИКС: 🇺🇸\n"
        "ТЕКСТ: SEC одобрила восемь спотовых ETF на Ethereum, торги стартуют "
        "23 июля. Это открывает институциональный доступ к ETH.\n"
        "ТИКЕРЫ: "
    )
    ai = FakeAIClient(reply=fields)
    writer = PostWriter(ai, enable_editor=False)
    post = await writer.write(
        make_item("x", source_name="Reuters", link="https://reuters.com/a")
    )
    assert "<code>" not in post.body
    assert post.body.startswith("🇺🇸 SEC одобрила")
    assert post.body.strip().endswith(
        '◉ Официально · <a href="https://reuters.com/a">Reuters</a>'
    )


async def test_no_prefix_when_empty():
    fields = "ПРЕФИКС: \nТЕКСТ: Рынок вырос на 3%.\nТИКЕРЫ: "
    ai = FakeAIClient(reply=fields)
    writer = PostWriter(ai, enable_editor=False)
    post = await writer.write(
        make_item("x", source_name="Blog", link="https://b.io/a")
    )
    assert post.body.startswith("Рынок вырос на 3%")
    assert "◎ Слух · " in post.body


def test_clean_prefix():
    assert _clean_prefix("⚡️") == "⚡️"
    assert _clean_prefix("⚡") == "⚡️"
    assert _clean_prefix("🇺🇸") == "🇺🇸"
    assert _clean_prefix("🇷🇺 что-то") == "🇷🇺"
    assert _clean_prefix("") == ""
    assert _clean_prefix("просто текст") == ""


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
        "префикс: ⚡️\nтекст: Раз два три\nтикеры: BTC: $1 (↑1%)"
    )
    assert f["ПРЕФИКС"] == "⚡️"
    assert f["ТЕКСТ"] == "Раз два три"
    assert f["ТИКЕРЫ"] == "BTC: $1 (↑1%)"


def test_render_fallback_when_fields_missing():
    item = make_item("Fallback text", source_name="SomeBlog", link="https://d.co/a")
    body = _render_post({}, item)
    assert body.startswith("Fallback text")
    assert "<code>" not in body  # no ticker line
    assert body.strip().endswith(
        '◎ Слух · <a href="https://d.co/a">SomeBlog</a>'
    )


def test_html_is_escaped():
    fields = "ТЕКСТ: 5 < 10 > 3 рост A & B\nТИКЕРЫ: "
    body = _render_post(_parse_fields(fields), make_item(
        "x", source_name="A&B", link="https://a.com"))
    assert "&lt;" in body
    assert "&gt;" in body
    assert "&amp;" in body


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
    assert sanitize_text("затрагивает主要ые активы") == "затрагиваетые активы"
    assert sanitize_text("высокое ↑ бычье BTC 100000") == (
        "высокое ↑ бычье BTC 100000"
    )
    assert "日本" not in sanitize_text("рынок 日本 растёт")
    assert sanitize_text("цена $100 и €50 · BTC") == "цена $100 и €50 · BTC"


def test_render_strips_cjk_from_fields():
    fields = _parse_fields(
        "ТЕКСТ: Цена выросла на 5%主要 за день.\nТИКЕРЫ: BTC: $1主要 (↑1%)"
    )
    body = _render_post(fields, make_item("x", source_name="CoinDesk",
                                          link="https://coindesk.com/a"))
    assert "主要" not in body


def test_strip_urls():
    assert _strip_urls("текст https://a.com/x хвост").strip() == "текст  хвост".strip()
    assert "http" not in _strip_urls("see http://x.io now")
    assert "t.me" not in _strip_urls("канал t.me/foo тут")


def test_strip_forbidden_phrases():
    assert "Суть:" not in _strip_forbidden("Суть: Биткоин вырос")
    assert "Метка:" not in _strip_forbidden("Метка: официально")
    assert "Время:" not in _strip_forbidden("Время: 12:00")
    assert "не указана" not in _strip_forbidden("Дата не указана сегодня")


async def test_render_removes_forbidden_and_urls_in_body():
    fields = "ТЕКСТ: Суть: Биткоин вырос на 10%. Подробнее https://x.io/a\nТИКЕРЫ: "
    ai = FakeAIClient(reply=fields)
    writer = PostWriter(ai, enable_editor=False)
    post = await writer.write(make_item("x", source_name="Blog",
                                        link="https://b.io/a"))
    assert "Суть:" not in post.body
    assert "https://x.io" not in post.body


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
