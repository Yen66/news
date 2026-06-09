"""The PreEventScheduler — drives the calendar against the wall clock.

One tick = one ``EventCalendar.due_alerts()`` query → publish-and-mark per
unfired alert. Designed to be cheap and idempotent so that:

- a duplicate tick is harmless (DB PK + in-memory set both guard);
- a Telegram failure leaves the alert UNMARKED so the next tick (still
  inside the grace window) retries it without producing a duplicate;
- a process restart inside a fire-window cannot double-send, because the
  in-memory fired set is rehydrated from ``load_fired_alerts()`` on start.

No AI calls. Strictly mechanical. Live publishing is gated upstream by
``ENABLE_PRE_EVENT_ALERTS`` — if the flag is off, this class is not even
instantiated.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional, Set, Tuple

from ..db.repository import Repository
from ..telegram.client import TelegramClient
from .calendar import EventCalendar
from .formatter import format_alert
from .models import AlertDue

log = logging.getLogger(__name__)

# Type aliases for clarity.
_FiredKey = Tuple[str, str]
_AdminAlerter = Callable[[str], "asyncio.Future"]  # type: ignore[name-defined]


class PreEventScheduler:
    """Process due pre-event alerts and publish them to Telegram.

    Single-instance, single-process. On Render free we always run one
    container, but every operation is still PK-idempotent at the DB layer
    so a hypothetical double-run cannot duplicate alerts.
    """

    def __init__(
        self,
        calendar: EventCalendar,
        repo: Repository,
        telegram: TelegramClient,
        *,
        grace: timedelta,
        admin_alerter: Optional[_AdminAlerter] = None,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._calendar = calendar
        self._repo = repo
        self._telegram = telegram
        self._grace = grace
        self._alert_admin = admin_alerter
        self._clock = clock
        self._fired: Set[_FiredKey] = set()
        self._hydrated = False
        # Running counts for observability (status endpoint, admin digest).
        self.alerts_sent: int = 0
        self.alerts_failed: int = 0
        self.last_tick_utc: Optional[datetime] = None

    async def hydrate(self) -> None:
        """Load the already-fired ledger from Postgres into the in-memory set.

        Idempotent — called once at startup. The in-memory set is a fast
        path; the DB primary key on ``(event_id, offset_label)`` is the
        canonical guard.
        """
        if self._hydrated:
            return
        self._fired = await self._repo.load_fired_alerts()
        self._hydrated = True
        log.info(
            "PreEventScheduler hydrated: %d alert(s) already fired, "
            "%d active event(s) in calendar.",
            len(self._fired),
            sum(1 for e in self._calendar.events if e.is_active),
        )

    def is_fired(self, due: AlertDue) -> bool:
        return (due.event_id, due.offset_label) in self._fired

    async def tick(self) -> int:
        """One scheduler iteration. Returns the number of alerts sent."""
        if not self._hydrated:
            await self.hydrate()
        now = self._clock()
        self.last_tick_utc = now
        sent_this_tick = 0
        for due in self._calendar.due_alerts(now, self._grace):
            if self.is_fired(due):
                continue
            if await self._process_one(due, now):
                sent_this_tick += 1
        return sent_this_tick

    async def _process_one(self, due: AlertDue, now: datetime) -> bool:
        """Publish a single due alert. Mark fired ONLY on success."""
        text = format_alert(due)
        log.info(
            "Pre-event alert preparing: event=%s offset=%s lead=%.1fmin "
            "title=%r",
            due.event_id,
            due.offset_label,
            (due.event.scheduled_utc - now).total_seconds() / 60.0,
            due.event.title,
        )
        try:
            sent = await self._telegram.publish(text)
        except Exception as exc:  # noqa: BLE001 - never let one alert kill the loop
            self.alerts_failed += 1
            log.exception(
                "Pre-event alert send raised: event=%s offset=%s",
                due.event_id, due.offset_label,
            )
            if self._alert_admin is not None:
                try:
                    await self._alert_admin(
                        f"Pre-event alert failed (event={due.event_id} "
                        f"offset={due.offset_label}): {exc}"
                    )
                except Exception:  # pragma: no cover - alerter is best-effort
                    pass
            return False
        if not sent:
            # Telegram returned a non-200; logged with hint by the client.
            self.alerts_failed += 1
            log.error(
                "Pre-event alert publish failed (event=%s offset=%s) — will "
                "retry next tick while still inside grace.",
                due.event_id, due.offset_label,
            )
            return False
        # Persist + cache only after a confirmed publish.
        inserted = await self._repo.mark_alert_fired(
            due.event_id, due.offset_label
        )
        self._fired.add((due.event_id, due.offset_label))
        self.alerts_sent += 1
        log.info(
            "Pre-event alert SENT: event=%s offset=%s newly_marked=%s",
            due.event_id, due.offset_label, inserted,
        )
        return True

    # --- observability -----------------------------------------------------
    def status(self) -> dict:
        upcoming = []
        if self._hydrated:
            for e in self._calendar.upcoming(self._clock(), limit=5):
                upcoming.append({
                    "event_id": e.event_id,
                    "title": e.title,
                    "scheduled_utc": e.scheduled_utc.isoformat(),
                    "importance": e.importance.value,
                    "offsets": list(e.offsets),
                })
        return {
            "hydrated": self._hydrated,
            "alerts_sent": self.alerts_sent,
            "alerts_failed": self.alerts_failed,
            "fired_recorded": len(self._fired),
            "last_tick_utc": (
                self.last_tick_utc.isoformat() if self.last_tick_utc else None
            ),
            "upcoming": upcoming,
        }
