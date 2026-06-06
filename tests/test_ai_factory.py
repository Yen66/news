import pytest

from src.ai.factory import AIClient, AllProvidersExhausted, _is_quota_error
from src.config import Config, ProviderConfig, TelegramConfig


def _config(providers):
    return Config(
        telegram=TelegramConfig("t", "@c", "1"),
        providers=providers,
        database_url="",
        poll_interval_seconds=30,
        queue_max_size=10,
        enable_editor=True,
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
