"""Data model for the pre-event alert calendar.

An :class:`Event` is a single scheduled, market-moving event (FOMC, CPI,
Jackson Hole, …). The calendar is the source of truth; these objects are
pure value types with no I/O.

Alert cadence is driven by ``importance``:

- ``CRITICAL`` (FOMC / CPI / NFP / SEC ETF decisions) -> 24h + 1h
- ``STANDARD`` (ECB / BOJ)                            -> 1h
- ``SPECIAL``  (manual-only: Jackson Hole, Powell testimony, major SEC
  hearings, pre-announced major Trump speeches)       -> 1h

Per-event ``offsets`` may override the importance default.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum


class Importance(str, Enum):
    CRITICAL = "critical"   # 24h + 1h
    STANDARD = "standard"   # 1h
    SPECIAL = "special"     # manual-only, 1h


# The only alert offsets we support. Label -> lead time before the event.
OFFSET_TIMEDELTAS: dict[str, timedelta] = {
    "24h": timedelta(hours=24),
    "1h": timedelta(hours=1),
}

# Default offsets per importance tier (finalised alert design).
DEFAULT_OFFSETS: dict[Importance, tuple[str, ...]] = {
    Importance.CRITICAL: ("24h", "1h"),
    Importance.STANDARD: ("1h",),
    Importance.SPECIAL: ("1h",),
}

# Statuses an event may carry.
VALID_STATUSES = {"scheduled", "cancelled"}


def canonical_offsets(labels) -> tuple[str, ...]:
    """Return offsets ordered longest-lead-first (24h before 1h), de-duplicated.

    Canonical ordering makes alert emission and tests deterministic.
    """
    seen = []
    for label in sorted(set(labels), key=lambda l: OFFSET_TIMEDELTAS[l],
                        reverse=True):
        seen.append(label)
    return tuple(seen)


@dataclass(frozen=True)
class Event:
    """A scheduled market-moving event.

    ``scheduled_utc`` is always a timezone-aware UTC datetime (the loader
    converts from local time + IANA tz). ``type`` is a stable slug used in
    the deterministic ``event_id``.
    """

    type: str
    title: str
    scheduled_utc: datetime
    importance: Importance
    offsets: tuple[str, ...]
    source_url: str = ""
    consensus: str = ""
    status: str = "scheduled"

    @property
    def event_id(self) -> str:
        """Stable, deterministic id: ``<type>:<YYYYMMDDTHHMMZ>``.

        Independent of YAML order and unchanged across reloads, so the
        dedup ledger never double-fires or loses track of an event.
        """
        return f"{self.type}:{self.scheduled_utc.strftime('%Y%m%dT%H%MZ')}"

    @property
    def is_active(self) -> bool:
        return self.status == "scheduled"


@dataclass(frozen=True)
class AlertDue:
    """A single (event, offset) alert whose fire-window is open now."""

    event: Event
    offset_label: str
    target_utc: datetime  # scheduled_utc - offset lead time

    @property
    def event_id(self) -> str:
        return self.event.event_id
