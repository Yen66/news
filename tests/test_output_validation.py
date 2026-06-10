"""Phase 6 — deterministic AI-output validation.

Token salad, two-word fragments, echoed labels and placeholders must never
reach Telegram. Legitimate (even terse) posts must still publish.
"""
import pytest

from src.ai.writer import (
    MalformedPostError,
    PostWriter,
    _validate_body,
)
from tests.conftest import FakeAIClient, make_item


# --- unit: _validate_body --------------------------------------------------

MALFORMED = [
    "Суротмасвород",                       # single gibberish token
    "О предложений",                       # two-word fragment
    "",                                    # empty
    "   ",                                 # whitespace only
    "BTC BTC BTC BTC",                     # repeated token
    "As an AI language model I cannot",    # model error text
    "Lorem ipsum dolor sit amet",          # placeholder
]


def test_validate_rejects_malformed():
    for text in MALFORMED:
        ok, reason = _validate_body(text)
        assert not ok, f"accepted malformed: {text!r}"


VALID = [
    "Рынок вырос на 3%",
    "ФРС снизила ставку на 25 базисных пунктов",
    "Биткоин и эфир потеряли $390 млрд за неделю, худший обвал с краха FTX",
    "SEC одобрила восемь спотовых ETF на Ethereum",
]


def test_validate_accepts_valid():
    for text in VALID:
        ok, reason = _validate_body(text)
        assert ok, f"rejected valid: {text!r} ({reason})"


# --- integration: writer raises MalformedPostError -------------------------

async def test_writer_raises_on_gibberish():
    fields = "ПРЕФИКС: \nТЕКСТ: Суротмасвород\nТИКЕРЫ: "
    writer = PostWriter(FakeAIClient(reply=fields), enable_editor=False)
    with pytest.raises(MalformedPostError):
        await writer.write(make_item("Bitcoin update",
                                     link="https://b.io/a"))


async def test_writer_raises_on_two_word_fragment():
    fields = "ПРЕФИКС: \nТЕКСТ: О предложений\nТИКЕРЫ: "
    writer = PostWriter(FakeAIClient(reply=fields), enable_editor=False)
    with pytest.raises(MalformedPostError):
        await writer.write(make_item("Bitcoin update",
                                     link="https://b.io/a"))


async def test_writer_accepts_valid_body():
    fields = "ПРЕФИКС: \nТЕКСТ: Биткоин вырос на 5% до $70 000.\nТИКЕРЫ: "
    writer = PostWriter(FakeAIClient(reply=fields), enable_editor=False)
    post = await writer.write(make_item("Bitcoin update",
                                        link="https://b.io/a"))
    assert "Биткоин вырос" in post.body


# --- integration: processor drops malformed without alert/seen -------------

async def test_processor_drops_malformed(fake_telegram):
    from src.db.repository import InMemoryRepository
    from src.pipeline.dedup import Deduplicator
    from src.pipeline.processor import Processor
    from src.pipeline.throttle import DailyBudget

    fields = "ПРЕФИКС: \nТЕКСТ: Суротмасвород\nТИКЕРЫ: "
    writer = PostWriter(FakeAIClient(reply=fields), enable_editor=False)
    repo = InMemoryRepository()
    dedup = Deduplicator()
    proc = Processor(writer, fake_telegram, repo, dedup, DailyBudget(100))

    item = make_item("Bitcoin rallies above 70k")
    published = await proc.process_one(item)

    assert published is False
    assert fake_telegram.published == []      # nothing published
    assert fake_telegram.alerts == []         # no admin spam
    assert not dedup.is_duplicate(item)       # not marked seen -> can retry
