import pytest

from src.ai.factory import (
    AIClient,
    AllProvidersExhausted,
    _is_quota_error,
    _retry_after_seconds,
)
from src.config import Config, ProviderConfig, TelegramConfig, _DEFAULT_MODELS


def _config(providers):
    return Config(
        telegram=TelegramConfig("t", "@c", "1"),
        providers=providers,
        database_url="",
        poll_interval_seconds=30,
        queue_max_size=10,
        max_new_per_cycle=5,
        max_article_age_hours=24,
        story_dedup_window_hours=6.0,
        enable_editor=True,
        ai_call_min_interval_seconds=0.0,
        daily_ai_call_budget=100,
        request_timeout_seconds=10,
        http_port=10000,
        log_level="INFO",
        dry_run=True,
    )


def _provider(name, prio):
    return ProviderConfig(
        name=name,
        base_url="https://x",
        api_key="key",
        model="m",
        priority=prio,
        enabled=True,
    )


class _QuotaError(Exception):
    status_code = 429


async def _fail_quota(self, *a, **k):
    raise _QuotaError("rate limit exceeded")


def test_is_quota_error_classification():
    assert _is_quota_error(_QuotaError("rate limit"))
    assert _is_quota_error(RuntimeError("429 Too Many Requests"))
    assert not _is_quota_error(RuntimeError("some other failure"))


async def test_rotates_on_quota_error(monkeypatch):
    cfg = _config([_provider("groq", 1), _provider("cerebras", 2)])
    client = AIClient(cfg)

    # First provider always hits quota; second succeeds.
    async def groq_fail(*a, **k):
        raise _QuotaError("quota")

    async def cerebras_ok(*a, **k):
        return "ok-text"

    client._providers[0].complete = groq_fail  # type: ignore[assignment]
    client._providers[1].complete = cerebras_ok  # type: ignore[assignment]

    text, provider = await client.complete("sys", "user")
    assert text == "ok-text"
    assert provider == "cerebras"


async def test_all_exhausted_raises(monkeypatch):
    cfg = _config([_provider("groq", 1), _provider("cerebras", 2)])
    client = AIClient(cfg)

    async def always_fail(*a, **k):
        raise _QuotaError("quota")

    for p in client._providers:
        p.complete = always_fail  # type: ignore[assignment]

    with pytest.raises(AllProvidersExhausted):
        await client.complete("sys", "user")


def test_cerebras_default_model_name():
    # Cerebras uses "llama3.3-70b" (no hyphen after llama), unlike Groq.
    assert _DEFAULT_MODELS["cerebras"] == "llama3.3-70b"
    assert _DEFAULT_MODELS["groq"] == "llama-3.3-70b-versatile"


def test_retry_after_parsing():
    class _H(Exception):
        def __init__(self):
            self.response = type("R", (), {"headers": {"retry-after": "4"}})()

    assert _retry_after_seconds(_H()) == 4.0

    class _B(Exception):
        body = {"error": {"retry_after_seconds": 7}}

    assert _retry_after_seconds(_B()) == 7.0
    assert _retry_after_seconds(RuntimeError("Please try again in 3s")) == 3.0
    assert _retry_after_seconds(RuntimeError("try again in 500ms")) == 0.5
    assert _retry_after_seconds(RuntimeError("no hint here")) is None


async def test_retries_once_with_retry_after_then_succeeds(monkeypatch):
    cfg = _config([_provider("groq", 1), _provider("cerebras", 2)])
    client = AIClient(cfg)
    calls = {"n": 0}

    class _RL(Exception):
        status_code = 429
        body = {"retry_after_seconds": 0}  # 0s wait keeps the test instant

    async def groq_then_ok(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _RL()
        return "recovered"

    client._providers[0].complete = groq_then_ok  # type: ignore[assignment]
    text, provider = await client.complete("s", "u")
    assert text == "recovered"
    assert provider == "groq"           # retried same provider, did not rotate
    assert calls["n"] == 2


async def test_rotates_when_no_retry_after(monkeypatch):
    cfg = _config([_provider("groq", 1), _provider("cerebras", 2)])
    client = AIClient(cfg)

    class _RL(Exception):
        status_code = 429  # no retry-after hint anywhere

    async def groq_fail(*a, **k):
        raise _RL()

    async def cerebras_ok(*a, **k):
        return "ok"

    client._providers[0].complete = groq_fail  # type: ignore[assignment]
    client._providers[1].complete = cerebras_ok  # type: ignore[assignment]
    text, provider = await client.complete("s", "u")
    assert text == "ok"
    assert provider == "cerebras"


def test_provider_order_by_priority():
    cfg = _config([_provider("openrouter", 3), _provider("groq", 1)])
    client = AIClient(cfg)
    assert client.provider_names == ["groq", "openrouter"]


def test_disabled_provider_excluded():
    p_disabled = ProviderConfig("gemini", "u", "k", "m", 4, enabled=False)
    p_no_key = ProviderConfig("groq", "u", "", "m", 1, enabled=True)
    cfg = _config([p_disabled, p_no_key, _provider("cerebras", 2)])
    client = AIClient(cfg)
    assert client.provider_names == ["cerebras"]
