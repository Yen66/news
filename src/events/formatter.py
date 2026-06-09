"""Calendar-event formatter — posts styled as regular CMW_News content.

Deterministic, no AI. Per-event-type templates carry the editorial framing
(lead + tail); the importance tier picks the marker emoji and gates whether
a curated consensus line is shown. Today/tomorrow tense comes purely from
the offset label (``24h`` -> tomorrow, ``1h`` -> today), so the formatter is
pure and side-effect free.

There is no time block, no countdown wording, no source link in the body —
calendar posts read like normal channel posts about an upcoming event, not
like scheduler notifications.
"""
from __future__ import annotations

import html

from .models import AlertDue, Importance


# Importance tier -> leading marker emoji.
_MARKERS = {
    Importance.CRITICAL: "🚨",
    Importance.STANDARD: "📅",
    Importance.SPECIAL: "⚠️",
}

# Per-event-type editorial templates.
#   lead_tomorrow: first sentence for a 24h (next-day) post; falls back to
#                  lead_today when omitted (e.g. SPECIAL has no 24h offset).
#   lead_today:    first sentence for a 1h (same-day) post.
#   tail:          contextual second/third sentence; always shown if set.
#   source:        the right-hand label after "◉ Calendar · ".
# To support a new SPECIAL type without touching anything else, add a row
# here. Unknown types fall through to a generic title-based line.
_TEMPLATES: dict[str, dict[str, str]] = {
    "fomc": {
        "lead_tomorrow": "Завтра ФРС объявит решение по процентной ставке.",
        "lead_today": "ФРС сегодня объявит решение по процентной ставке.",
        "tail": (
            "Внимание к комментариям Пауэлла и сигналам по дальнейшей "
            "траектории ставок."
        ),
        "source": "Federal Reserve",
    },
    "cpi": {
        "lead_tomorrow": "Завтра в США выйдет отчёт по инфляции (CPI).",
        "lead_today": "Сегодня в США выходит отчёт по инфляции (CPI).",
        "tail": (
            "Данные определят ожидания по политике ФРС; реакция в долларе, "
            "доходностях трежерис и крипте — самая быстрая."
        ),
        "source": "BLS",
    },
    "nfp": {
        "lead_tomorrow": (
            "Завтра в США выйдет отчёт по занятости (NFP) и уровню "
            "безработицы."
        ),
        "lead_today": (
            "Сегодня в США выходит отчёт по занятости (NFP) и уровню "
            "безработицы."
        ),
        "tail": (
            "Цифры по созданию рабочих мест и пересмотры предыдущих "
            "месяцев задают тон ожиданиям по ставке ФРС."
        ),
        "source": "BLS",
    },
    "ecb": {
        "lead_tomorrow": "Завтра ЕЦБ объявит решение по процентной ставке.",
        "lead_today": "Сегодня ЕЦБ объявит решение по процентной ставке.",
        "tail": (
            "Внимание к комментариям Лагард и сигналам по траектории ставок "
            "в еврозоне."
        ),
        "source": "ECB",
    },
    "boj": {
        "lead_tomorrow": (
            "Завтра Банк Японии объявит решение по процентной ставке."
        ),
        "lead_today": (
            "Сегодня Банк Японии объявит решение по процентной ставке."
        ),
        "tail": (
            "Внимание к сигналам по нормализации денежно-кредитной политики "
            "и реакции в иене."
        ),
        "source": "BOJ",
    },
    # --- SPECIAL examples ---------------------------------------------------
    "trump_speech": {
        "lead_today": "Сегодня выступает Дональд Трамп.",
        "tail": (
            "Рынки ждут заявлений по тарифам, торговой политике и "
            "отношениям с Китаем; возможен рост волатильности в крипте "
            "и акциях."
        ),
        "source": "White House",
    },
    "powell_testimony": {
        "lead_today": (
            "Сегодня Пауэлл выступит с показаниями в Конгрессе."
        ),
        "tail": (
            "Внимание к сигналам по траектории ставок и оценке состояния "
            "экономики."
        ),
        "source": "Federal Reserve",
    },
    "jackson_hole": {
        "lead_today": (
            "Сегодня в Джексон-Хоуле выступает председатель ФРС."
        ),
        "tail": (
            "Рынки ждут программных тезисов по дальнейшей политике; "
            "историческая площадка для разворотов."
        ),
        "source": "Federal Reserve",
    },
}

_FOOTER_LABEL = "◉ Calendar"


def _generic_lead(title: str, offset: str) -> str:
    when = "Завтра" if offset == "24h" else "Сегодня"
    # Escape because ``title`` comes from the YAML and could carry &/< if a
    # curator pastes a stray symbol.
    return f"{when} — {html.escape(title)}."


def format_alert(due: AlertDue) -> str:
    """Render an AlertDue into a Telegram-HTML post styled as channel content.

    Layout:

        {marker} {lead}. [Консенсус: {…}.] {tail}.

        ◉ Calendar · {Source}

    The marker reflects the importance tier (CRITICAL=🚨, STANDARD=📅,
    SPECIAL=⚠️). Consensus is shown only for CRITICAL events that carry a
    curated forecast in ``event.consensus``. The footer drops the source
    suffix entirely when no template is registered for the event type, so
    unknown SPECIAL entries never produce an awkward ``· Calendar`` tail.
    """
    e = due.event
    esc = html.escape
    marker = _MARKERS.get(e.importance, _MARKERS[Importance.STANDARD])

    tmpl = _TEMPLATES.get(e.type)
    if tmpl is None:
        lead = _generic_lead(e.title, due.offset_label)
        tail = ""
        source = ""
    else:
        if due.offset_label == "24h":
            lead = tmpl.get("lead_tomorrow") or tmpl.get("lead_today") or \
                _generic_lead(e.title, due.offset_label)
        else:
            lead = tmpl.get("lead_today") or _generic_lead(e.title, "1h")
        tail = tmpl.get("tail", "")
        source = tmpl.get("source", "")

    # Consensus only for CRITICAL events that explicitly carry a forecast.
    consensus = ""
    if e.importance == Importance.CRITICAL and e.consensus:
        consensus = f" Консенсус: {esc(e.consensus)}."

    body = lead + consensus
    if tail:
        body = f"{body} {tail}"
    body_line = f"{marker} {body}"

    footer = _FOOTER_LABEL + (f" · {esc(source)}" if source else "")
    return f"{body_line}\n\n{footer}"
