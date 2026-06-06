"""AI provider factory + cross-provider rotation.

All configured providers are OpenAI-compatible, so we build ONE
``AsyncOpenAI`` client per provider (only ``base_url`` / ``api_key`` /
``model`` differ) and keep them ordered by priority. On a 429 / quota /
rate-limit error we automatically rotate to the next usable provider.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from openai import AsyncOpenAI

from ..config import Config, ProviderConfig

log = logging.getLogger(__name__)


class AllProvidersExhausted(RuntimeError):
    """Raised when every provider failed (usually all hit their quota)."""


def _is_quota_error(exc: Exception) -> bool:
    """Heuristic: should we rotate to the next provider for this error?"""
    # openai.RateLimitError / APIStatusError expose status_code.
    status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if status in (429, 402, 503):
        return True
    text = str(exc).lower()
    return any(
        kw in text
        for kw in (
            "rate limit",
            "rate_limit",
            "quota",
            "insufficient",
            "too many requests",
            "429",
            "capacity",
            "overloaded",
        )
    )


class _ProviderClient:
    """A single provider plus its lazily-built AsyncOpenAI client."""

    def __init__(self, cfg: ProviderConfig, timeout: int) -> None:
        self.cfg = cfg
        self._timeout = timeout
        self._client: Optional[AsyncOpenAI] = None

    @property
    def name(self) -> str:
        return self.cfg.name

    @property
    def client(self) -> AsyncOpenAI:
        if self._client is None:
            self._client = AsyncOpenAI(
                api_key=self.cfg.api_key,
                base_url=self.cfg.base_url,
                timeout=self._timeout,
                max_retries=0,  # rotation is handled by us, not the SDK
            )
        return self._client

    async def complete(
        self, system: str, user: str, temperature: float, max_tokens: int
    ) -> str:
        resp = await self.client.chat.completions.create(
            model=self.cfg.model,
            temperature=temperature,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return (resp.choices[0].message.content or "").strip()


class AIClient:
    """Facade that rotates across providers on quota errors."""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._providers: List[_ProviderClient] = [
            _ProviderClient(p, config.request_timeout_seconds)
            for p in config.usable_providers
        ]
        if not self._providers:
            log.warning(
                "No usable AI providers configured. The bot will not be able "
                "to write posts until at least one provider key is set."
            )

    @property
    def available(self) -> bool:
        return bool(self._providers)

    @property
    def provider_names(self) -> List[str]:
        return [p.name for p in self._providers]

    async def complete(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.4,
        max_tokens: int = 800,
    ) -> tuple[str, str]:
        """Return ``(text, provider_name)``, rotating on quota errors.

        Raises :class:`AllProvidersExhausted` if every provider fails.
        """
        if not self._providers:
            raise AllProvidersExhausted("no providers configured")

        last_exc: Optional[Exception] = None
        for provider in self._providers:
            try:
                text = await provider.complete(
                    system, user, temperature, max_tokens
                )
                if text:
                    return text, provider.name
                last_exc = RuntimeError(f"{provider.name} returned empty text")
            except Exception as exc:  # noqa: BLE001 - we classify below
                last_exc = exc
                if _is_quota_error(exc):
                    log.warning(
                        "Provider %s hit quota/limit, rotating to next: %s",
                        provider.name,
                        exc,
                    )
                    continue
                log.warning(
                    "Provider %s failed (%s), rotating to next.",
                    provider.name,
                    exc,
                )
                continue

        raise AllProvidersExhausted(
            f"all providers failed; last error: {last_exc}"
        ) from last_exc

    async def aclose(self) -> None:
        for provider in self._providers:
            if provider._client is not None:
                try:
                    await provider._client.close()
                except Exception:  # pragma: no cover - best effort
                    pass


def build_ai_client(config: Config) -> AIClient:
    return AIClient(config)
