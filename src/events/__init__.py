"""Pre-event alert subsystem (calendar, scheduling, formatting).

Phase 0/1 ship the calendar model, loader/validation and the dedup-backed
repository support. Live publishing (the scheduler task) is added in a later
phase and is gated behind ``ENABLE_PRE_EVENT_ALERTS`` (default False).
"""
from .models import (
    AlertDue,
    DEFAULT_OFFSETS,
    Event,
    Importance,
    OFFSET_TIMEDELTAS,
)
from .calendar import CalendarError, EventCalendar
from .formatter import format_alert
from .scheduler import PreEventScheduler

__all__ = [
    "AlertDue",
    "DEFAULT_OFFSETS",
    "Event",
    "Importance",
    "OFFSET_TIMEDELTAS",
    "CalendarError",
    "EventCalendar",
    "PreEventScheduler",
    "format_alert",
]
