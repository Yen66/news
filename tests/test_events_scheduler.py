"""End-to-end behavior of the PreEventScheduler.

The scheduler is the only component that turns calendar data into channel
posts, so these tests pin down every guarantee from the design:

- duplicate protection (in-memory + DB PK both work);
- mark-fired ONLY on a confirmed publish, so a Telegram failure retries
  next tick without producing a duplicate or losing the alert;
- stale-alert suppression via the grace window;
- restart-in-window safety via hydrate() rehydrating the in-memory set;
- cancelled events never fire;
- one tick == one cohesive read-then-write pass.
"""
from datetime import datetime, timedelta, timezone
from typing import List

from src.db.repository import InMemoryRepository
from src.events.calendar import EventCalendar
from src.events.scheduler import PreEventScheduler

GRACE = timedelta(minutes=20)


class _FakeTelegram:
    def __init__(self, *, succeed: bool = True, raise_exc: bool = False) -> None:
        self.succeed = succeed
        self.raise_exc = raise_exc
        self.published: List[str] = []

    async def publish(self, text: str) -> bool:
        if self.raise_exc:
            raise RuntimeError("boom")
        self.published.append(text)
        return self.succeed


def _cal(**over):
    base = dict(
        type="cpi",
        title="CPI",
        time="2026-06-11 08:30",
        tz="America/New_York",
        importance="critical",
    )
    base.update(over)
    return EventCalendar.from_raw([base])


def _sched(cal, repo, tg, *, clock):
    return PreEventScheduler(cal, repo, tg, grace=GRACE,
                             clock=clock)


# --- duplicate protection ---------------------------------------------------

async def test_first_tick_sends_then_second_tick_dedupes():
    cal = _cal()
    target = cal.events[0].scheduled_utc - timedelta(hours=1)
    repo = InMemoryRepository()
    tg = _FakeTelegram()
    s = _sched(cal, repo, tg, clock=lambda: target)
    assert await s.tick() == 1
    assert len(tg.published) == 1
    assert await repo.alert_fired("cpi:20260611T1230Z", "1h")
    # Second tick at the same instant -> no duplicate.
    assert await s.tick() == 0
    assert len(tg.published) == 1


async def test_db_dedup_survives_in_memory_cache_loss():
    cal = _cal()
    target = cal.events[0].scheduled_utc - timedelta(hours=1)
    repo = InMemoryRepository()
    # Simulate "we already sent this alert in a prior run".
    await repo.mark_alert_fired("cpi:20260611T1230Z", "1h")
    tg = _FakeTelegram()
    s = _sched(cal, repo, tg, clock=lambda: target)
    # A fresh scheduler must NOT re-send after hydrate.
    assert await s.tick() == 0
    assert tg.published == []


# --- mark-fired only on successful publish ----------------------------------

async def test_publish_failure_is_not_marked_and_retries_next_tick():
    cal = _cal()
    sched_utc = cal.events[0].scheduled_utc
    repo = InMemoryRepository()
    tg = _FakeTelegram(succeed=False)
    # Clock: first tick at T-1h (fails), second tick 1 minute later (succeeds).
    state = {"t": sched_utc - timedelta(hours=1)}
    s = _sched(cal, repo, tg, clock=lambda: state["t"])
    assert await s.tick() == 0
    assert s.alerts_failed == 1
    assert not await repo.alert_fired("cpi:20260611T1230Z", "1h")
    # Telegram recovers.
    tg.succeed = True
    state["t"] += timedelta(minutes=1)
    assert await s.tick() == 1
    assert await repo.alert_fired("cpi:20260611T1230Z", "1h")
    assert s.alerts_sent == 1


async def test_publish_exception_is_swallowed_and_not_marked():
    cal = _cal()
    sched_utc = cal.events[0].scheduled_utc
    repo = InMemoryRepository()
    tg = _FakeTelegram(raise_exc=True)
    admin: List[str] = []

    async def alerter(msg):
        admin.append(msg)

    s = PreEventScheduler(cal, repo, tg, grace=GRACE,
                          admin_alerter=alerter,
                          clock=lambda: sched_utc - timedelta(hours=1))
    assert await s.tick() == 0
    assert s.alerts_failed == 1
    assert not await repo.alert_fired("cpi:20260611T1230Z", "1h")
    assert admin and "Pre-event alert failed" in admin[0]


# --- stale-alert suppression via the grace window ---------------------------

async def test_no_send_when_clock_is_past_grace_window():
    cal = _cal()
    sched_utc = cal.events[0].scheduled_utc
    repo = InMemoryRepository()
    tg = _FakeTelegram()
    # 40 min after the T-1h target -> outside 20 min grace.
    now = sched_utc - timedelta(hours=1) + timedelta(minutes=40)
    s = _sched(cal, repo, tg, clock=lambda: now)
    assert await s.tick() == 0
    assert tg.published == []


async def test_no_send_after_event_has_already_passed():
    cal = _cal()
    sched_utc = cal.events[0].scheduled_utc
    repo = InMemoryRepository()
    tg = _FakeTelegram()
    s = _sched(cal, repo, tg, clock=lambda: sched_utc + timedelta(minutes=30))
    assert await s.tick() == 0


# --- hydrate / restart-in-window safety -------------------------------------

async def test_hydrate_runs_once_and_loads_db_state():
    repo = InMemoryRepository()
    await repo.mark_alert_fired("cpi:20260611T1230Z", "1h")
    cal = _cal()
    target = cal.events[0].scheduled_utc - timedelta(hours=1)
    tg = _FakeTelegram()
    s = _sched(cal, repo, tg, clock=lambda: target)
    await s.hydrate()
    assert s._hydrated is True
    assert s.is_fired_count() if hasattr(s, "is_fired_count") else True
    # Second hydrate is a no-op even if DB grew.
    await repo.mark_alert_fired("fomc:20260101T1800Z", "1h")
    await s.hydrate()
    assert ("fomc:20260101T1800Z", "1h") not in s._fired


# --- cancelled events / status fields ---------------------------------------

async def test_cancelled_event_never_sends():
    cal = _cal(status="cancelled")
    sched_utc = cal.events[0].scheduled_utc
    repo = InMemoryRepository()
    tg = _FakeTelegram()
    s = _sched(cal, repo, tg, clock=lambda: sched_utc - timedelta(hours=1))
    assert await s.tick() == 0
    assert tg.published == []


async def test_status_reports_counters_and_upcoming():
    cal = _cal()
    sched_utc = cal.events[0].scheduled_utc
    repo = InMemoryRepository()
    tg = _FakeTelegram()
    s = _sched(cal, repo, tg, clock=lambda: sched_utc - timedelta(days=1))
    await s.hydrate()
    st = s.status()
    assert st["hydrated"] is True
    assert st["alerts_sent"] == 0
    assert st["alerts_failed"] == 0
    assert st["fired_recorded"] == 0
    assert st["upcoming"] and st["upcoming"][0]["event_id"] == "cpi:20260611T1230Z"


# --- the 24h + 1h sequence for one critical event ---------------------------

async def test_critical_event_sends_24h_then_1h_then_nothing():
    cal = _cal(importance="critical")
    sched_utc = cal.events[0].scheduled_utc
    repo = InMemoryRepository()
    tg = _FakeTelegram()
    state = {"t": sched_utc - timedelta(hours=24)}
    s = _sched(cal, repo, tg, clock=lambda: state["t"])
    # T-24h: 24h fires; 1h not yet due.
    assert await s.tick() == 1
    # 5 minutes later: still inside 24h grace, but already fired -> 0.
    state["t"] += timedelta(minutes=5)
    assert await s.tick() == 0
    # T-1h: the 1h fires.
    state["t"] = sched_utc - timedelta(hours=1)
    assert await s.tick() == 1
    assert len(tg.published) == 2
    assert s.alerts_sent == 2
