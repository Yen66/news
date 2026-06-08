from datetime import datetime, timezone

from src.events.models import (
    DEFAULT_OFFSETS,
    Event,
    Importance,
    canonical_offsets,
)


def _event(type_="cpi", when=None, importance=Importance.CRITICAL,
           offsets=("24h", "1h")):
    when = when or datetime(2026, 6, 11, 12, 30, tzinfo=timezone.utc)
    return Event(
        type=type_, title="t", scheduled_utc=when,
        importance=importance, offsets=offsets,
    )


def test_event_id_format_and_stability():
    e = _event(when=datetime(2026, 6, 11, 12, 30, tzinfo=timezone.utc))
    assert e.event_id == "cpi:20260611T1230Z"
    # Same inputs -> same id (deterministic across reloads).
    assert e.event_id == _event(
        when=datetime(2026, 6, 11, 12, 30, tzinfo=timezone.utc)
    ).event_id


def test_event_id_differs_by_time_and_type():
    a = _event("cpi", datetime(2026, 6, 11, 12, 30, tzinfo=timezone.utc))
    b = _event("cpi", datetime(2026, 7, 11, 12, 30, tzinfo=timezone.utc))
    c = _event("fomc", datetime(2026, 6, 11, 12, 30, tzinfo=timezone.utc))
    assert a.event_id != b.event_id
    assert a.event_id != c.event_id


def test_default_offsets_per_tier():
    assert DEFAULT_OFFSETS[Importance.CRITICAL] == ("24h", "1h")
    assert DEFAULT_OFFSETS[Importance.STANDARD] == ("1h",)
    assert DEFAULT_OFFSETS[Importance.SPECIAL] == ("1h",)


def test_canonical_offsets_orders_longest_first_and_dedups():
    assert canonical_offsets(["1h", "24h", "1h"]) == ("24h", "1h")
    assert canonical_offsets(["1h"]) == ("1h",)


def test_is_active_reflects_status():
    assert _event().is_active
    cancelled = Event(
        type="cpi", title="t",
        scheduled_utc=datetime(2026, 6, 11, 12, 30, tzinfo=timezone.utc),
        importance=Importance.CRITICAL, offsets=("1h",), status="cancelled",
    )
    assert not cancelled.is_active
