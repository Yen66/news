"""Load, validate and query the pre-event calendar.

The calendar is a hand-curated YAML file (``calendar.yaml``) — the single
source of truth. Loading is strict: any malformed entry raises
:class:`CalendarError` listing every problem, so a bad deploy fails loudly
rather than silently dropping alerts.

Timezone handling is explicit: each event gives a local ``time`` plus an IANA
``tz`` (e.g. ``America/New_York``), converted to aware UTC via ``zoneinfo``
(DST-correct). ``time: UTC`` is supported by setting ``tz: UTC``.

``due_alerts(now, grace)`` is pure computation and the heart of the
"no stale / no premature" guarantee:

- an offset fires only inside ``[target, target + grace]``;
- once ``now`` is past the event (or past ``target + grace``) the offset is
  never emitted — so a process that was asleep can never send a
  "CPI in 1 hour" alert after CPI has already printed.

Deduplication against already-sent alerts lives in the repository, not here.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, List, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .models import (
    AlertDue,
    DEFAULT_OFFSETS,
    Event,
    Importance,
    OFFSET_TIMEDELTAS,
    VALID_STATUSES,
    canonical_offsets,
)

log = logging.getLogger(__name__)

_TIME_FORMATS = ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S")


class CalendarError(Exception):
    """Raised when the calendar file is malformed or fails validation."""


def _parse_local_time(value: str) -> datetime:
    for fmt in _TIME_FORMATS:
        try:
            return datetime.strptime(value, fmt)
        except (ValueError, TypeError):
            continue
    raise ValueError(
        f"time {value!r} not in 'YYYY-MM-DD HH:MM' format"
    )


def _build_event(raw: dict, index: int) -> Event:
    """Validate one raw mapping and build an :class:`Event`.

    Raises ``ValueError`` with a human-readable message on any problem; the
    caller aggregates these into a single :class:`CalendarError`.
    """
    if not isinstance(raw, dict):
        raise ValueError(f"entry #{index} is not a mapping")

    where = f"entry #{index}"

    etype = str(raw.get("type", "")).strip()
    if not etype:
        raise ValueError(f"{where}: missing required 'type'")
    where = f"{where} (type={etype!r})"

    title = str(raw.get("title", "")).strip()
    if not title:
        raise ValueError(f"{where}: missing required 'title'")

    raw_importance = str(raw.get("importance", "")).strip().lower()
    try:
        importance = Importance(raw_importance)
    except ValueError:
        valid = ", ".join(i.value for i in Importance)
        raise ValueError(
            f"{where}: invalid importance {raw_importance!r} (expected: {valid})"
        )

    time_str = raw.get("time")
    tz_str = str(raw.get("tz", "")).strip()
    if not time_str:
        raise ValueError(f"{where}: missing required 'time'")
    if not tz_str:
        raise ValueError(f"{where}: missing required 'tz' (IANA name or 'UTC')")
    try:
        naive = _parse_local_time(str(time_str))
    except ValueError as exc:
        raise ValueError(f"{where}: {exc}")
    try:
        tzinfo = ZoneInfo(tz_str)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        raise ValueError(f"{where}: unknown timezone {tz_str!r}")
    scheduled_utc = naive.replace(tzinfo=tzinfo).astimezone(timezone.utc)

    raw_offsets = raw.get("offsets")
    if raw_offsets is None:
        offsets = DEFAULT_OFFSETS[importance]
    else:
        if not isinstance(raw_offsets, (list, tuple)) or not raw_offsets:
            raise ValueError(f"{where}: 'offsets' must be a non-empty list")
        bad = [o for o in raw_offsets if o not in OFFSET_TIMEDELTAS]
        if bad:
            valid = ", ".join(OFFSET_TIMEDELTAS)
            raise ValueError(
                f"{where}: unknown offset(s) {bad} (valid: {valid})"
            )
        offsets = canonical_offsets(raw_offsets)

    status = str(raw.get("status", "scheduled")).strip().lower()
    if status not in VALID_STATUSES:
        valid = ", ".join(sorted(VALID_STATUSES))
        raise ValueError(f"{where}: invalid status {status!r} (expected: {valid})")

    return Event(
        type=etype,
        title=title,
        scheduled_utc=scheduled_utc,
        importance=importance,
        offsets=offsets,
        tz_name=tz_str,
        source_url=str(raw.get("source_url", "")).strip(),
        consensus=str(raw.get("consensus", "")).strip(),
        status=status,
    )


@dataclass
class EventCalendar:
    events: List[Event] = field(default_factory=list)

    # --- construction ------------------------------------------------------
    @classmethod
    def from_raw(cls, raw_entries: Iterable[dict]) -> "EventCalendar":
        """Build (and validate) a calendar from already-parsed mappings.

        Aggregates all validation problems — including duplicate event ids —
        into a single :class:`CalendarError`.
        """
        events: List[Event] = []
        errors: List[str] = []
        seen_ids: dict[str, int] = {}
        for i, raw in enumerate(raw_entries or []):
            try:
                event = _build_event(raw, i)
            except ValueError as exc:
                errors.append(str(exc))
                continue
            if event.event_id in seen_ids:
                errors.append(
                    f"entry #{i}: duplicate event_id {event.event_id!r} "
                    f"(also entry #{seen_ids[event.event_id]})"
                )
                continue
            seen_ids[event.event_id] = i
            events.append(event)
        if errors:
            raise CalendarError(
                "calendar validation failed:\n  - " + "\n  - ".join(errors)
            )
        return cls(events=events)

    @classmethod
    def load(cls, path: str | Path) -> "EventCalendar":
        """Load and validate the calendar from a YAML file.

        An empty/missing file yields an empty calendar (no events, no error)
        so the subsystem degrades quietly when nothing is scheduled.
        """
        import yaml

        p = Path(path)
        if not p.exists():
            log.warning("Calendar file %s not found — no events loaded.", p)
            return cls(events=[])
        text = p.read_text(encoding="utf-8")
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise CalendarError(f"could not parse {p}: {exc}")
        if data is None:
            return cls(events=[])
        if not isinstance(data, list):
            raise CalendarError(
                f"{p}: top level must be a list of events, got {type(data).__name__}"
            )
        cal = cls.from_raw(data)
        log.info("Loaded %d calendar event(s) from %s.", len(cal.events), p)
        return cal

    # --- queries -----------------------------------------------------------
    def upcoming(self, now: datetime, limit: int = 10) -> List[Event]:
        """Active events still in the future, soonest first."""
        future = [
            e for e in self.events
            if e.is_active and e.scheduled_utc > now
        ]
        future.sort(key=lambda e: e.scheduled_utc)
        return future[:limit]

    def due_alerts(
        self, now: datetime, grace: timedelta
    ) -> List[AlertDue]:
        """Return alerts whose fire-window ``[target, target+grace]`` is open.

        Guarantees:
        - cancelled events and events already in the past are skipped;
        - an offset is emitted only inside its grace window, so neither
          premature nor stale ("already happened") alerts are produced.
        Caller is responsible for dedup against previously-fired alerts.
        """
        due: List[AlertDue] = []
        for event in self.events:
            if not event.is_active:
                continue
            if now >= event.scheduled_utc:
                continue  # event passed -> suppress all pre-event offsets
            for label in event.offsets:
                target = event.scheduled_utc - OFFSET_TIMEDELTAS[label]
                if target <= now <= target + grace:
                    due.append(AlertDue(event, label, target))
        # Soonest event first, longest lead first within an event.
        due.sort(key=lambda d: (d.event.scheduled_utc, -OFFSET_TIMEDELTAS[d.offset_label]))
        return due
