from datetime import datetime, timedelta, timezone

import pytest

from src.events.calendar import CalendarError, EventCalendar
from src.events.models import Importance

GRACE = timedelta(minutes=20)


def _raw(**over):
    base = {
        "type": "cpi",
        "title": "Инфляция (CPI)",
        "time": "2026-06-11 08:30",
        "tz": "America/New_York",
        "importance": "critical",
    }
    base.update(over)
    return base


# --- loading & timezone conversion -----------------------------------------

def test_local_time_converted_to_utc():
    cal = EventCalendar.from_raw([_raw()])
    e = cal.events[0]
    # 08:30 EDT (UTC-4 in June) -> 12:30 UTC.
    assert e.scheduled_utc == datetime(2026, 6, 11, 12, 30, tzinfo=timezone.utc)
    assert e.scheduled_utc.tzinfo is timezone.utc


def test_dst_difference_handled():
    # January is EST (UTC-5): 08:30 -> 13:30 UTC.
    winter = EventCalendar.from_raw([_raw(time="2026-01-14 08:30")]).events[0]
    assert winter.scheduled_utc.hour == 13
    # July is EDT (UTC-4): 08:30 -> 12:30 UTC.
    summer = EventCalendar.from_raw([_raw(time="2026-07-15 08:30")]).events[0]
    assert summer.scheduled_utc.hour == 12


def test_utc_timezone_supported():
    e = EventCalendar.from_raw([_raw(tz="UTC", time="2026-06-11 12:00")]).events[0]
    assert e.scheduled_utc == datetime(2026, 6, 11, 12, 0, tzinfo=timezone.utc)


def test_offsets_default_by_importance():
    crit = EventCalendar.from_raw([_raw(importance="critical")]).events[0]
    std = EventCalendar.from_raw([_raw(importance="standard")]).events[0]
    spec = EventCalendar.from_raw([_raw(importance="special")]).events[0]
    assert crit.offsets == ("24h", "1h")
    assert std.offsets == ("1h",)
    assert spec.offsets == ("1h",)


def test_offsets_override_is_canonicalised():
    e = EventCalendar.from_raw([_raw(offsets=["1h", "24h"])]).events[0]
    assert e.offsets == ("24h", "1h")


# --- validation errors ------------------------------------------------------

def test_missing_required_fields_raise():
    for missing in ("type", "title", "time", "tz", "importance"):
        bad = _raw()
        del bad[missing]
        with pytest.raises(CalendarError):
            EventCalendar.from_raw([bad])


def test_invalid_importance_raises():
    with pytest.raises(CalendarError):
        EventCalendar.from_raw([_raw(importance="mega")])


def test_invalid_timezone_raises():
    with pytest.raises(CalendarError):
        EventCalendar.from_raw([_raw(tz="Mars/Phobos")])


def test_bad_time_format_raises():
    with pytest.raises(CalendarError):
        EventCalendar.from_raw([_raw(time="June 11 2026")])


def test_unknown_offset_raises():
    with pytest.raises(CalendarError):
        EventCalendar.from_raw([_raw(offsets=["48h"])])


def test_invalid_status_raises():
    with pytest.raises(CalendarError):
        EventCalendar.from_raw([_raw(status="maybe")])


def test_duplicate_event_id_raises():
    with pytest.raises(CalendarError):
        EventCalendar.from_raw([_raw(), _raw()])  # same type + time


def test_error_message_aggregates_all_problems():
    with pytest.raises(CalendarError) as exc:
        EventCalendar.from_raw([_raw(importance="x"), _raw(tz="Bad/Zone")])
    msg = str(exc.value)
    assert "importance" in msg and "timezone" in msg


# --- upcoming ---------------------------------------------------------------

def test_upcoming_orders_future_only():
    now = datetime(2026, 6, 10, 0, 0, tzinfo=timezone.utc)
    cal = EventCalendar.from_raw([
        _raw(type="fomc", time="2026-06-17 14:00"),
        _raw(type="cpi", time="2026-06-11 08:30"),
        _raw(type="old", time="2026-06-01 08:30"),  # past
    ])
    up = cal.upcoming(now)
    assert [e.type for e in up] == ["cpi", "fomc"]


def test_upcoming_excludes_cancelled():
    now = datetime(2026, 6, 10, 0, 0, tzinfo=timezone.utc)
    cal = EventCalendar.from_raw([_raw(time="2026-06-11 08:30", status="cancelled")])
    assert cal.upcoming(now) == []


# --- due_alerts: grace window, no stale, no premature -----------------------

def _cal_one(**over):
    return EventCalendar.from_raw([_raw(importance="critical", **over)])


def test_due_fires_at_24h_window_open():
    cal = _cal_one()  # scheduled 2026-06-11 12:30 UTC
    sched = cal.events[0].scheduled_utc
    now = sched - timedelta(hours=24)  # exactly T-24h
    due = cal.due_alerts(now, GRACE)
    labels = {d.offset_label for d in due}
    assert labels == {"24h"}


def test_due_fires_at_1h_window_open():
    cal = _cal_one()
    sched = cal.events[0].scheduled_utc
    now = sched - timedelta(minutes=55)  # inside the T-1h grace window
    due = cal.due_alerts(now, GRACE)
    assert {d.offset_label for d in due} == {"1h"}


def test_no_premature_alert_before_window():
    cal = _cal_one()
    sched = cal.events[0].scheduled_utc
    now = sched - timedelta(hours=2)  # before T-1h, after T-24h+grace
    assert cal.due_alerts(now, GRACE) == []


def test_no_stale_alert_past_grace():
    cal = _cal_one()
    sched = cal.events[0].scheduled_utc
    # 40 min after T-24h target — outside the 20-min grace -> not emitted.
    now = sched - timedelta(hours=24) + timedelta(minutes=40)
    assert {d.offset_label for d in cal.due_alerts(now, GRACE)} == set()


def test_no_alert_after_event_passed():
    cal = _cal_one()
    sched = cal.events[0].scheduled_utc
    now = sched + timedelta(minutes=5)  # event already happened
    assert cal.due_alerts(now, GRACE) == []


def test_grace_boundary_inclusive():
    cal = _cal_one()
    sched = cal.events[0].scheduled_utc
    now = sched - timedelta(hours=1) + GRACE  # exactly target+grace
    assert {d.offset_label for d in cal.due_alerts(now, GRACE)} == {"1h"}


def test_cancelled_event_never_due():
    cal = _cal_one(status="cancelled")
    sched = cal.events[0].scheduled_utc
    now = sched - timedelta(hours=1)
    assert cal.due_alerts(now, GRACE) == []


def test_special_event_only_1h():
    cal = EventCalendar.from_raw([
        _raw(type="jackson_hole", importance="special", time="2026-08-21 10:00",
             tz="America/Denver")
    ])
    sched = cal.events[0].scheduled_utc
    # At T-24h: nothing (special has no 24h offset).
    assert cal.due_alerts(sched - timedelta(hours=24), GRACE) == []
    # At T-1h: the single 1h alert.
    assert {d.offset_label for d in cal.due_alerts(
        sched - timedelta(minutes=50), GRACE)} == {"1h"}


# --- file loading -----------------------------------------------------------

def test_load_missing_file_is_empty(tmp_path):
    cal = EventCalendar.load(tmp_path / "nope.yaml")
    assert cal.events == []


def test_load_real_calendar_file():
    cal = EventCalendar.load("src/events/calendar.yaml")
    assert cal.events, "shipped calendar should parse and be non-empty"
    types = {e.type for e in cal.events}
    # Production calendar carries only verified event families (BOJ excluded —
    # no official decision time; SEC ETF excluded — no confirmed deadline).
    assert {"cpi", "fomc", "nfp", "ecb"} <= types
    # Every shipped event is valid and UTC-aware.
    for e in cal.events:
        assert e.scheduled_utc.tzinfo is timezone.utc


def test_load_rejects_non_list(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("type: cpi\ntitle: x\n", encoding="utf-8")
    with pytest.raises(CalendarError):
        EventCalendar.load(p)
