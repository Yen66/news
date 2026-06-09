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


def test_24h_template_includes_lead_and_consensus():
    msg = format_alert(_due(_ev(consensus="ожидается 3,2% г/г"), "24h"))
    assert "<b>Инфляция в США (CPI)</b>" in msg
    assert "через 24 часа" in msg
    assert "Консенсус: ожидается 3,2% г/г" in msg


def test_24h_omits_consensus_block_when_empty():
    msg = format_alert(_due(_ev(consensus=""), "24h"))
    assert "Консенсус" not in msg


def test_1h_never_includes_consensus_even_if_present():
    msg = format_alert(_due(_ev(consensus="placeholder"), "1h"))
    assert "через 1 час" in msg
    assert "Консенсус" not in msg


def test_includes_source_link_when_present():
    msg = format_alert(_due(_ev(source_url="https://bls.gov/x"), "1h"))
    assert '<a href="https://bls.gov/x">Источник</a>' in msg


def test_omits_source_link_when_absent():
    msg = format_alert(_due(_ev(source_url=""), "1h"))
    assert "Источник" not in msg


def test_local_time_shows_msk_and_event_local():
    # 12:30 UTC -> 15:30 MSK -> 08:30 New York (EDT, June).
    msg = format_alert(_due(_ev(), "1h"))
    assert "15:30 МСК" in msg
    assert "08:30" in msg
    assert "NEW YORK" in msg


def test_utc_event_shows_msk_only():
    ev = _ev(tz_name="UTC")
    msg = format_alert(_due(ev, "1h"))
    assert "15:30 МСК" in msg
    assert "UTC" not in msg.split("Старт:")[1].split("\n")[0]


def test_html_escaping_in_title_and_consensus():
    ev = _ev(title="A & B <c>", consensus="x < y & z")
    msg = format_alert(_due(ev, "24h"))
    assert "A &amp; B &lt;c&gt;" in msg
    assert "x &lt; y &amp; z" in msg


def test_special_event_1h_template_same_shape():
    # The tier does NOT change the template — the calendar already chose
    # WHICH alerts fire. Shape stays uniform for visual recognisability.
    ev = _ev(type="jackson_hole", title="Джексон-Хоул",
             importance=Importance.SPECIAL, offsets=("1h",))
    msg = format_alert(_due(ev, "1h"))
    assert "<b>Джексон-Хоул</b>" in msg
    assert "через 1 час" in msg


def test_message_has_no_url_when_source_missing_no_blank_trailing_section():
    msg = format_alert(_due(_ev(source_url=""), "1h"))
    # No blank line followed by another blank line.
    assert "\n\n\n" not in msg
