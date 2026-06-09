"""Deterministic Russian alert templates — no AI, no judgment, pure code.

Three offsets × three tiers produce a small, predictable set of messages.
HTML-escaped for ``parse_mode=HTML`` (Telegram); link preview is disabled by
the publisher.
"""
from __future__ import annotations

import html
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .models import AlertDue, Importance


# Channel audience is Russian-speaking — Moscow time is the canonical clock.
MSK = ZoneInfo("Europe/Moscow")

# Lead-time wording per offset label.
_LEAD_RU = {
    "24h": "через 24 часа",
    "1h": "через 1 час",
}

_MONTHS_RU = [
    "", "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]


def _fmt_local(dt: datetime, tz: ZoneInfo) -> str:
    local = dt.astimezone(tz)
    return f"{local.day} {_MONTHS_RU[local.month]}, {local:%H:%M}"


def format_alert(due: AlertDue) -> str:
    """Render an AlertDue into a Telegram-HTML message.

    Layout — small, identical shape per offset, only fields change:

        <b>{title}</b> — {lead time}

        Старт: {date+time MSK} МСК · {date+time event-local} {LOCAL_TZ}
        Консенсус: {…}          ← 24h only, if event.consensus is set

        <a href="{source}">Источник</a>   ← only if source_url is set

    Tier choice (critical/standard/special) does NOT change the template —
    we keep it deterministic and uniform so the channel's pre-event style is
    instantly recognisable. The tier already drives WHICH alerts fire.
    """
    e = due.event
    esc = html.escape

    lead = _LEAD_RU.get(due.offset_label, due.offset_label)
    sched = e.scheduled_utc

    try:
        event_local = ZoneInfo(e.tz_name)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        event_local = ZoneInfo("UTC")

    msk_str = _fmt_local(sched, MSK)
    if e.tz_name and e.tz_name != "UTC" and event_local != MSK:
        local_str = _fmt_local(sched, event_local)
        # Short tz tag — last segment of the IANA name (New_York -> NEW_YORK).
        tz_short = e.tz_name.split("/")[-1].replace("_", " ").upper()
        time_line = f"Старт: {msk_str} МСК · {local_str} {tz_short}"
    else:
        time_line = f"Старт: {msk_str} МСК"

    lines = [f"<b>{esc(e.title)}</b> — {lead}", "", time_line]
    if due.offset_label == "24h" and e.consensus:
        lines.append(f"Консенсус: {esc(e.consensus)}")
    if e.source_url:
        lines += ["", f'<a href="{esc(e.source_url, quote=True)}">Источник</a>']
    return "\n".join(lines)
