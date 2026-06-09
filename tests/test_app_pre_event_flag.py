"""Verify the ENABLE_PRE_EVENT_ALERTS feature flag wiring in NewsBotApp.

Goal: when the flag is OFF the calendar isn't loaded, the scheduler is
never created and the status payload says nothing about pre-events. When
the flag is ON the scheduler is wired and surfaced in /status.
"""
from pathlib import Path

from src.app import NewsBotApp
from src.config import load_config


def _setenv(monkeypatch):
    for k in ("DATABASE_URL", "GROQ_API_KEY", "CEREBRAS_API_KEY",
              "OPENROUTER_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("DRY_RUN", "true")
    monkeypatch.setenv("BOT_TOKEN", "t")
    monkeypatch.setenv("CHANNEL_ID", "@c")


def test_flag_off_means_no_scheduler(monkeypatch):
    _setenv(monkeypatch)
    monkeypatch.delenv("ENABLE_PRE_EVENT_ALERTS", raising=False)
    app = NewsBotApp(load_config())
    assert app._pre_event_scheduler is None
    assert "pre_event_alerts" not in app.status()


def test_flag_on_loads_calendar_and_creates_scheduler(monkeypatch):
    _setenv(monkeypatch)
    monkeypatch.setenv("ENABLE_PRE_EVENT_ALERTS", "true")
    app = NewsBotApp(load_config())
    assert app._pre_event_scheduler is not None
    assert "pre_event_alerts" in app.status()


def test_bad_calendar_disables_subsystem_but_does_not_crash(
    monkeypatch, tmp_path
):
    _setenv(monkeypatch)
    bad = tmp_path / "bad.yaml"
    bad.write_text("- type: cpi\n  importance: bogus\n", encoding="utf-8")
    monkeypatch.setenv("ENABLE_PRE_EVENT_ALERTS", "true")
    monkeypatch.setenv("PRE_EVENT_CALENDAR_PATH", str(bad))
    app = NewsBotApp(load_config())
    # Subsystem failed loud (logs an ERROR) but startup keeps going.
    assert app._pre_event_scheduler is None
    assert "pre_event_alerts" not in app.status()
