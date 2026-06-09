"""Formatter tests — calendar events styled as regular CMW_News content.

Pin down:
- importance markers (🚨 / 📅 / ⚠️) per tier,
- 24h -> "Завтра", 1h -> "Сегодня" tense,
- consensus shown only for CRITICAL events with a curated forecast,
- no countdown wording, no time block, no body link,
- footer ``◉ Calendar · <source>`` (source dropped when unknown).
"""
from datetime import datetime, timezone

from src.events.formatter import format_alert
from src.events.models import AlertDue, Event, Importance


def _ev(**over):
    base = dict(
        type="cpi",
        title="Инфляция в США (CPI)",
        scheduled_utc=datetime(2026, 6, 11, 12, 30, tzinfo=timezone.utc),
        importance=Importance.CRITICAL,
        offsets=("24h", "1h"),
        tz_name="America/New_York",
    )
    base.update(over)
    return Event(**base)


def _due(ev, offset="1h"):
    return AlertDue(ev, offset, ev.scheduled_utc)


# --- markers ----------------------------------------------------------------

def test_critical_marker_is_red_siren():
    msg = format_alert(_due(_ev(type="fomc"), "1h"))
    assert msg.startswith("🚨 ")


def test_standard_marker_is_calendar():
    ev = _ev(type="ecb", importance=Importance.STANDARD, offsets=("1h",))
    msg = format_alert(_due(ev, "1h"))
    assert msg.startswith("📅 ")


def test_special_marker_is_warning():
    ev = _ev(type="trump_speech", importance=Importance.SPECIAL,
             offsets=("1h",), title="Выступление Трампа")
    msg = format_alert(_due(ev, "1h"))
    assert msg.startswith("⚠️ ")


# --- tense from offset only -------------------------------------------------

def test_24h_uses_tomorrow_phrasing():
    msg = format_alert(_due(_ev(type="fomc"), "24h"))
    assert "Завтра" in msg
    assert "Сегодня" not in msg


def test_1h_uses_today_phrasing():
    msg = format_alert(_due(_ev(type="fomc"), "1h"))
    assert "сегодня" in msg.lower()
    assert "Завтра" not in msg


# --- no countdown / scheduler / time-block wording --------------------------

def test_no_countdown_or_scheduler_wording():
    msg = format_alert(_due(_ev(type="fomc"), "24h"))
    for forbidden in [
        "через 24", "через 1", "Старт:", "alert", "scheduler",
        "pre-event", "UTC", "МСК",
    ]:
        assert forbidden not in msg, f"forbidden token leaked: {forbidden!r}"


def test_no_html_link_in_body():
    # Even when the event carries a source_url, the body must not contain a
    # clickable link — calendar posts read like normal channel content.
    msg = format_alert(_due(_ev(
        type="fomc", source_url="https://www.federalreserve.gov/x"), "1h"))
    assert "<a " not in msg
    assert "href=" not in msg
    assert "https://" not in msg


# --- consensus rules --------------------------------------------------------

def test_consensus_shown_for_critical_with_value():
    ev = _ev(type="cpi", consensus="ожидается 3,2% г/г")
    msg = format_alert(_due(ev, "1h"))
    assert "Консенсус: ожидается 3,2% г/г" in msg


def test_consensus_omitted_when_empty_on_critical():
    msg = format_alert(_due(_ev(type="cpi", consensus=""), "1h"))
    assert "Консенсус" not in msg


def test_consensus_omitted_on_standard_even_if_set():
    ev = _ev(type="ecb", importance=Importance.STANDARD, offsets=("1h",),
             consensus="rate hold expected")
    msg = format_alert(_due(ev, "1h"))
    assert "Консенсус" not in msg


def test_consensus_omitted_on_special_even_if_set():
    ev = _ev(type="trump_speech", importance=Importance.SPECIAL,
             offsets=("1h",), consensus="not applicable")
    msg = format_alert(_due(ev, "1h"))
    assert "Консенсус" not in msg


def test_consensus_html_escaped():
    ev = _ev(type="cpi", consensus="A < B & C")
    msg = format_alert(_due(ev, "1h"))
    assert "A &lt; B &amp; C" in msg


# --- footer -----------------------------------------------------------------

def test_footer_has_calendar_label_and_known_source():
    msg = format_alert(_due(_ev(type="fomc"), "1h"))
    assert msg.rstrip().endswith("◉ Calendar · Federal Reserve")


def test_footer_per_known_type():
    cases = {
        "fomc": "Federal Reserve",
        "cpi": "BLS",
        "nfp": "BLS",
        "ecb": "ECB",
        "boj": "BOJ",
        "trump_speech": "White House",
    }
    for etype, src in cases.items():
        importance = (Importance.SPECIAL if etype == "trump_speech"
                      else Importance.STANDARD if etype in ("ecb", "boj")
                      else Importance.CRITICAL)
        ev = _ev(type=etype, importance=importance, offsets=("1h",))
        msg = format_alert(_due(ev, "1h"))
        assert msg.rstrip().endswith(f"◉ Calendar · {src}"), \
            f"{etype}: unexpected footer in {msg!r}"


def test_footer_drops_source_when_type_unknown():
    # Unknown SPECIAL types don't have a registered source label; the footer
    # must end at "Calendar" — never "Calendar · Calendar" or a stray dot.
    ev = _ev(type="g20_summit", importance=Importance.SPECIAL,
             offsets=("1h",), title="Саммит G20")
    msg = format_alert(_due(ev, "1h"))
    assert msg.rstrip().endswith("◉ Calendar")
    assert "Calendar · Calendar" not in msg
    assert "Calendar ·" not in msg.rstrip().splitlines()[-1] or \
        msg.rstrip().splitlines()[-1].endswith("Calendar")


# --- generic fallback for unknown types -------------------------------------

def test_unknown_type_falls_back_to_title_lead():
    ev = _ev(type="g20_summit", importance=Importance.SPECIAL,
             offsets=("1h",), title="Саммит G20 в Риме")
    msg = format_alert(_due(ev, "1h"))
    assert "Сегодня — Саммит G20 в Риме." in msg


def test_unknown_type_24h_uses_tomorrow_fallback():
    ev = _ev(type="g20_summit", title="Саммит G20")
    msg = format_alert(_due(ev, "24h"))
    assert "Завтра — Саммит G20." in msg


# --- structural shape -------------------------------------------------------

def test_post_has_body_blank_then_footer():
    msg = format_alert(_due(_ev(type="fomc"), "1h"))
    lines = msg.split("\n")
    assert len(lines) >= 3
    assert lines[-2] == ""             # blank line before footer
    assert lines[-1].startswith("◉ Calendar")
    # Body line is non-empty and starts with the marker.
    assert lines[0].startswith("🚨 ")
