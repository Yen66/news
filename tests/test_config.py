import importlib

import src.config as config_mod
from src.config import normalize_channel_id


def test_normalize_adds_at_to_bare_username():
    assert normalize_channel_id("CMW_News") == "@CMW_News"


def test_normalize_keeps_existing_at():
    assert normalize_channel_id("@CMW_News") == "@CMW_News"


def test_normalize_passes_numeric_id():
    assert normalize_channel_id("-1001234567890") == "-1001234567890"


def test_normalize_strips_tme_url():
    assert normalize_channel_id("https://t.me/CMW_News") == "@CMW_News"
    assert normalize_channel_id("t.me/CMW_News") == "@CMW_News"


def test_normalize_empty():
    assert normalize_channel_id("") == ""
    assert normalize_channel_id("   ") == ""


def _reload(monkeypatch, env):
    for key in (
        "BOT_TOKEN", "TELEGRAM_BOT_TOKEN", "CHANNEL_ID", "TELEGRAM_CHANNEL_ID",
        "ADMIN_ID", "ADMIN_TELEGRAM_ID",
    ):
        monkeypatch.delenv(key, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return config_mod.load_config()


def test_load_config_accepts_short_names(monkeypatch):
    cfg = _reload(
        monkeypatch,
        {"BOT_TOKEN": "tok", "CHANNEL_ID": "CMW_News", "ADMIN_ID": "42"},
    )
    assert cfg.telegram.bot_token == "tok"
    assert cfg.telegram.channel_id == "@CMW_News"
    assert cfg.telegram.admin_id == "42"
    assert cfg.telegram.configured


def test_load_config_falls_back_to_legacy_names(monkeypatch):
    cfg = _reload(
        monkeypatch,
        {
            "TELEGRAM_BOT_TOKEN": "tok2",
            "TELEGRAM_CHANNEL_ID": "@Legacy",
            "ADMIN_TELEGRAM_ID": "7",
        },
    )
    assert cfg.telegram.bot_token == "tok2"
    assert cfg.telegram.channel_id == "@Legacy"
    assert cfg.telegram.admin_id == "7"


def test_short_name_takes_precedence(monkeypatch):
    cfg = _reload(
        monkeypatch,
        {"BOT_TOKEN": "new", "TELEGRAM_BOT_TOKEN": "old", "CHANNEL_ID": "@c"},
    )
    assert cfg.telegram.bot_token == "new"
