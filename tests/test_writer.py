from src.ai.writer import PostWriter, _format_footer, _ensure_label
from tests.conftest import FakeAIClient, make_item


async def test_writer_one_call_for_normal_post():
    ai = FakeAIClient(reply="Суть новости. Рост BTC.")
    writer = PostWriter(ai, enable_editor=True)
    item = make_item("Bitcoin rallies", impact=40, official=False)
    post = await writer.write(item)
    # Normal (not important) => single writer call, no editor.
    assert len(ai.calls) == 1
    assert not post.editor_used
    assert post.provider_used == "groq"
    assert "Источник:" in post.body
    assert "МСК" in post.body


async def test_writer_editor_runs_for_official():
    ai = FakeAIClient(reply="Официально. Суть. Падение акций.")
    writer = PostWriter(ai, enable_editor=True)
    item = make_item("SEC charges firm", official=True, impact=85)
    post = await writer.write(item)
    assert len(ai.calls) == 2  # writer + editor
    assert post.editor_used


async def test_writer_editor_disabled():
    ai = FakeAIClient(reply="Официально. Текст.")
    writer = PostWriter(ai, enable_editor=False)
    item = make_item("SEC charges firm", official=True, impact=85)
    post = await writer.write(item)
    assert len(ai.calls) == 1
    assert not post.editor_used


async def test_writer_editor_failure_falls_back_to_draft():
    ai = FakeAIClient(reply="Официально. Черновик.")
    ai.fail_times = 1  # writer succeeds, editor (2nd call) fails first
    # fail_times applies to the next call(s); writer is first call.
    writer = PostWriter(ai, enable_editor=True)
    # Make writer succeed and editor fail: set fail on second call only.
    ai.fail_times = 0
    # Simulate editor failure by monkeypatching after first call.
    calls = {"n": 0}
    orig_reply = ai.reply

    async def flaky(system, user, *, temperature=0.4, max_tokens=800):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("editor down")
        return orig_reply, "groq"

    ai.complete = flaky  # type: ignore[assignment]
    item = make_item("SEC charges firm", official=True, impact=85)
    post = await writer.write(item)
    assert not post.editor_used  # editor failed, draft kept
    assert "Официально" in post.body


def test_ensure_label_adds_when_missing():
    assert "Официально" in _ensure_label("Просто текст", official=True)
    assert "не подтверждено" in _ensure_label("Просто текст", official=False)


def test_ensure_label_keeps_existing():
    body = "Текст\n\nОфициально"
    assert _ensure_label(body, official=True) == body


def test_footer_has_msk_and_link():
    item = make_item("x", link="https://example.com/a")
    footer = _format_footer(item)
    assert "МСК" in footer
    assert "https://example.com/a" in footer
