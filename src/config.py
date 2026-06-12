"""Runtime configuration loaded from environment variables.

Everything tunable lives here so a second channel, a new language, paid
sources, or extra providers can be added later without touching the core.
No secret is ever hard-coded; all of them come from the environment (see
``.env.example``).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Optional

try:
    # Optional: load a local .env during development. In production (Render)
    # the variables are injected directly, so dotenv is not required.
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover - dotenv is optional
    pass


def _get(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _get_any(names: list[str], default: str = "") -> str:
    """Return the first non-empty env var among ``names``.

    Lets us accept short names (BOT_TOKEN, CHANNEL_ID, ADMIN_ID) while keeping
    the older TELEGRAM_*-prefixed names working as fallbacks.
    """
    for name in names:
        val = os.environ.get(name, "").strip()
        if val:
            return val
    return default


def _get_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "y"}


def normalize_channel_id(raw: str) -> str:
    """Normalise a Telegram channel id to a form the Bot API accepts.

    - Numeric ids (``-100123...``) are passed through unchanged.
    - A bare public username like ``CMW_News`` gets a leading ``@``.
    - A full URL like ``https://t.me/CMW_News`` or ``t.me/CMW_News`` is
      reduced to ``@CMW_News``.
    - An already-correct ``@CMW_News`` is left as-is.
    """
    value = raw.strip()
    if not value:
        return ""
    # Numeric chat id (possibly negative) — leave untouched.
    if value.lstrip("-").isdigit():
        return value
    # Strip a t.me URL down to the username.
    for prefix in ("https://t.me/", "http://t.me/", "t.me/"):
        if value.lower().startswith(prefix):
            value = value[len(prefix):]
            break
    value = value.lstrip("/")
    if value.startswith("@"):
        return value
    return "@" + value


def _get_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw.strip())
    except ValueError:
        return default


@dataclass(frozen=True)
class ProviderConfig:
    """One OpenAI-compatible AI provider.

    All providers speak the same protocol; only ``base_url``, ``api_key``
    and ``model`` differ. Providers are tried in ``priority`` order and the
    client rotates to the next one on a 429 / quota error.
    """

    name: str
    base_url: str
    api_key: str
    model: str
    priority: int
    enabled: bool = True

    @property
    def usable(self) -> bool:
        return self.enabled and bool(self.api_key) and bool(self.base_url)


@dataclass(frozen=True)
class TelegramConfig:
    bot_token: str
    channel_id: str
    admin_id: str
    language: str = "ru"

    @property
    def configured(self) -> bool:
        return bool(self.bot_token) and bool(self.channel_id)


@dataclass(frozen=True)
class Config:
    telegram: TelegramConfig
    providers: List[ProviderConfig]
    database_url: str
    poll_interval_seconds: int
    queue_max_size: int
    max_new_per_cycle: int
    max_article_age_hours: int
    story_dedup_window_hours: float
    enable_editor: bool
    ai_call_min_interval_seconds: float
    daily_ai_call_budget: int
    request_timeout_seconds: int
    http_port: int
    log_level: str
    dry_run: bool
    min_impact_to_publish: int = 45
    # --- Task 1.1 subject-level burst cap ---
    subject_cap_window_hours: float = 12.0
    max_per_subject: int = 2
    # --- pre-event alerts (calendar-driven, gated; live publishing later) ---
    enable_pre_event_alerts: bool = False
    pre_event_calendar_path: str = "src/events/calendar.yaml"
    pre_event_grace_minutes: int = 20
    pre_event_tick_seconds: int = 60

    @property
    def usable_providers(self) -> List[ProviderConfig]:
        return sorted(
            (p for p in self.providers if p.usable),
            key=lambda p: p.priority,
        )


# Default OpenAI-compatible endpoints for each provider. Override via env if
# a provider changes its URL or you want a different model.
_DEFAULT_BASE_URLS = {
    "groq": "https://api.groq.com/openai/v1",
    "cerebras": "https://api.cerebras.ai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
}

_DEFAULT_MODELS = {
    "groq": "llama-3.3-70b-versatile",
    "cerebras": "llama3.3-70b",
    "openrouter": "meta-llama/llama-3.3-70b-instruct:free",
    "gemini": "gemini-1.5-flash",
}


def _build_providers() -> List[ProviderConfig]:
    """Build the provider list in cross-provider rotation order.

    1) Groq      (primary, fast, generous free tier)
    2) Cerebras  (1M tokens/day, very fast — handles volume / Groq 429)
    3) OpenRouter (free models — safety net)
    4) Gemini    (kept in code but DISABLED by default for future use)
    """
    return [
        ProviderConfig(
            name="groq",
            base_url=_get("GROQ_BASE_URL", _DEFAULT_BASE_URLS["groq"]),
            api_key=_get("GROQ_API_KEY"),
            model=_get("GROQ_MODEL", _DEFAULT_MODELS["groq"]),
            priority=1,
            enabled=_get_bool("GROQ_ENABLED", True),
        ),
        ProviderConfig(
            name="cerebras",
            base_url=_get("CEREBRAS_BASE_URL", _DEFAULT_BASE_URLS["cerebras"]),
            api_key=_get("CEREBRAS_API_KEY"),
            model=_get("CEREBRAS_MODEL", _DEFAULT_MODELS["cerebras"]),
            priority=2,
            enabled=_get_bool("CEREBRAS_ENABLED", True),
        ),
        ProviderConfig(
            name="openrouter",
            base_url=_get("OPENROUTER_BASE_URL", _DEFAULT_BASE_URLS["openrouter"]),
            api_key=_get("OPENROUTER_API_KEY"),
            model=_get("OPENROUTER_MODEL", _DEFAULT_MODELS["openrouter"]),
            priority=3,
            enabled=_get_bool("OPENROUTER_ENABLED", True),
        ),
        ProviderConfig(
            name="gemini",
            base_url=_get("GEMINI_BASE_URL", _DEFAULT_BASE_URLS["gemini"]),
            api_key=_get("GEMINI_API_KEY"),
            model=_get("GEMINI_MODEL", _DEFAULT_MODELS["gemini"]),
            priority=4,
            # Disabled by default; flip GEMINI_ENABLED=true to use it later.
            enabled=_get_bool("GEMINI_ENABLED", False),
        ),
    ]


def load_config() -> Config:
    """Load configuration from the environment."""
    telegram = TelegramConfig(
        # Primary names: BOT_TOKEN / CHANNEL_ID. The TELEGRAM_*-prefixed names
        # are accepted as fallbacks for backwards compatibility.
        bot_token=_get_any(["BOT_TOKEN", "TELEGRAM_BOT_TOKEN"]),
        channel_id=normalize_channel_id(
            _get_any(["CHANNEL_ID", "TELEGRAM_CHANNEL_ID"])
        ),
        admin_id=_get_any(["ADMIN_ID", "ADMIN_TELEGRAM_ID"]),
        language=_get("CHANNEL_LANGUAGE", "ru"),
    )
    return Config(
        telegram=telegram,
        providers=_build_providers(),
        database_url=_get("DATABASE_URL"),
        poll_interval_seconds=_get_int("POLL_INTERVAL_SECONDS", 30),
        queue_max_size=_get_int("QUEUE_MAX_SIZE", 200),
        max_new_per_cycle=_get_int("MAX_NEW_PER_CYCLE", 3),
        max_article_age_hours=_get_int("MAX_ARTICLE_AGE_HOURS", 24),
        story_dedup_window_hours=float(
            _get_int("STORY_DEDUP_WINDOW_HOURS", 6)
        ),
        enable_editor=_get_bool("ENABLE_EDITOR", True),
        ai_call_min_interval_seconds=float(
            _get_int("AI_CALL_MIN_INTERVAL_SECONDS", 15)
        ),
        daily_ai_call_budget=_get_int("DAILY_AI_CALL_BUDGET", 1000),
        request_timeout_seconds=_get_int("REQUEST_TIMEOUT_SECONDS", 30),
        http_port=_get_int("PORT", 10000),
        log_level=_get("LOG_LEVEL", "INFO"),
        dry_run=_get_bool("DRY_RUN", False),
        min_impact_to_publish=_get_int("MIN_IMPACT_TO_PUBLISH", 45),
        subject_cap_window_hours=float(
            _get_int("SUBJECT_CAP_WINDOW_HOURS", 12)
        ),
        max_per_subject=_get_int("MAX_PER_SUBJECT", 2),
        enable_pre_event_alerts=_get_bool("ENABLE_PRE_EVENT_ALERTS", False),
        pre_event_calendar_path=_get(
            "PRE_EVENT_CALENDAR_PATH", "src/events/calendar.yaml"
        ),
        pre_event_grace_minutes=_get_int("PRE_EVENT_GRACE_MINUTES", 20),
        pre_event_tick_seconds=_get_int("PRE_EVENT_TICK_SECONDS", 60),
    )
