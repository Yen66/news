from src.ai.writer import PostWriter
from src.db.repository import InMemoryRepository
from src.pipeline.dedup import Deduplicator
from src.pipeline.processor import Processor, ProcessingQueue
from src.pipeline.throttle import DailyBudget
from tests.conftest import FakeAIClient, FakeTelegram, make_item


def _build(ai=None, telegram=None, budget_limit=100):
    ai = ai or FakeAIClient(reply="Суть. Рост BTC.")
    telegram = telegram or FakeTelegram()
    repo = InMemoryRepository()
    dedup = Deduplicator()
    budget = DailyBudget(budget_limit)
    writer = PostWriter(ai, enable_editor=True)
    proc = Processor(writer, telegram, repo, dedup, budget)
    return proc, telegram, repo, dedup, budget


async def test_process_publishes_and_persists():
    proc, telegram, repo, dedup, budget = _build()
    item = make_item("Bitcoin rallies above 70k")
    published = await proc.process_one(item)
    assert published
    assert len(telegram.published) == 1
    assert dedup.is_duplicate(item)
    assert len(repo.archived) == 1
    assert budget.used == 1


async def test_process_skips_known_duplicate():
    proc, telegram, repo, dedup, budget = _build()
    item = make_item("Repeat story")
    dedup.mark(item)
    published = await proc.process_one(item)
    assert not published
    assert telegram.published == []


async def test_exhausted_budget_skips_low_impact():
    proc, telegram, repo, dedup, budget = _build(budget_limit=1)
    budget.record()  # exhaust it
    low = make_item("Some minor crypto note", impact=30, official=False)
    assert not await proc.process_one(low)
    assert telegram.published == []


async def test_exhausted_budget_still_posts_official():
    proc, telegram, repo, dedup, budget = _build(budget_limit=1)
    budget.record()
    high = make_item("SEC emergency action", impact=90, official=True)
    assert await proc.process_one(high)
    assert len(telegram.published) == 1


class _FailingTelegram(FakeTelegram):
    async def publish(self, text: str) -> bool:
        self.published.append(text)  # record the attempt
        return False  # but report failure


async def test_failed_publish_is_not_marked_seen():
    telegram = _FailingTelegram()
    proc, _, repo, dedup, budget = _build(telegram=telegram)
    item = make_item("Bitcoin rallies above 70k")
    published = await proc.process_one(item)
    assert published is False
    # Must NOT be marked seen, and must NOT be archived, so it retries later.
    assert not dedup.is_duplicate(item)
    assert repo.archived == []


async def test_ai_call_spacing_enforced(monkeypatch):
    import src.pipeline.processor as proc_mod

    proc, telegram, repo, dedup, budget = _build()
    proc._ai_min_interval = 15.0

    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    # Pretend an AI call happened 1s ago via monotonic; expect ~14s wait.
    clock = {"t": 1000.0}
    monkeypatch.setattr(proc_mod.time, "monotonic", lambda: clock["t"])
    monkeypatch.setattr(proc_mod.asyncio, "sleep", fake_sleep)
    proc._last_ai_ts = 1000.0
    clock["t"] = 1001.0  # 1s elapsed

    await proc.process_one(make_item("Bitcoin rallies above 70k"))
    assert sleeps and abs(sleeps[0] - 14.0) < 0.01


async def test_no_spacing_when_interval_zero(monkeypatch):
    import src.pipeline.processor as proc_mod

    proc, telegram, repo, dedup, budget = _build()
    proc._ai_min_interval = 0.0
    slept = []
    monkeypatch.setattr(proc_mod.asyncio, "sleep",
                        lambda s: slept.append(s))
    await proc.process_one(make_item("Bitcoin rallies above 70k"))
    assert slept == []


async def test_queue_priority_orders_by_impact():
    q = ProcessingQueue(max_size=10)
    await q.put(make_item("low", impact=10, guid="l"))
    await q.put(make_item("high", impact=90, guid="h"))
    await q.put(make_item("mid", impact=50, guid="m"))
    first = await q.get()
    second = await q.get()
    third = await q.get()
    assert first.title == "high"
    assert second.title == "mid"
    assert third.title == "low"


async def test_queue_full_returns_false():
    q = ProcessingQueue(max_size=1)
    assert await q.put(make_item("a", guid="a"))
    assert not await q.put(make_item("b", guid="b"))
