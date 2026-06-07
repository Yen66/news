"""AI provider factory + cross-provider rotation.

All configured providers are OpenAI-compatible, so we build ONE
``AsyncOpenAI`` client per provider (only ``base_url`` / ``api_key`` /
``model`` differ) and keep them ordered by priority. On a 429 / quota /
rate-limit error we automatically rotate to the next usable provider.
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import List, Optional

from openai import AsyncOpenAI

from ..config import Config, ProviderConfig

log = logging.getLogger(__name__)

# Never wait longer than this on a Retry-After before rotating providers.
MAX_RETRY_AFTER_SECONDS = 30.0


class AllProvidersExhausted(RuntimeError):
    """Raised when every provider failed (usually all hit their quota)."""


def _retry_after_seconds(exc: Exception) -> Optional[float]:
    """Extract a retry-after hint (seconds) from a 429, if the provider gave one.

    Checks the HTTP ``Retry-After`` header, structured error body metadata
    (``retry_after_seconds`` / ``retry_after``), and common message phrasings.
    """
    # 1) HTTP Retry-After header (openai SDK exposes .response).
    resp = getattr(exc, "response", None)
    headers = getattr(resp, "headers", None) if resp is not None else None
    if headers:
        raw = headers.get("retry-after") or headers.get("Retry-After")
        if raw:
            try:
                return float(raw)
            except (TypeError, ValueError):
                pass
    # 2) Structured body metadata.
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        candidates = [body, body.get("error") if isinstance(body.get("error"), dict) else {}]
        for d in candidates:
            for key in ("retry_after_seconds", "retry_after", "retryAfter"):
                val = d.get(key)
                if val is not None:
                    try:
                        return float(val)
                    except (TypeError, ValueError):
                        pass
    # 3) Parse from the error text.
    text = str(exc)
    m = re.search(r"retry[_-]?after[_-]?seconds[\"'\s:=]+([0-9.]+)", text, re.I)
    if m:
        return float(m.group(1))
    m = re.search(r"try again in ([0-9.]+)\s*s(?:econds)?\b", text, re.I)
    if m:
        return float(m.group(1))
    m = re.search(r"try again in ([0-9.]+)\s*ms\b", text, re.I)
    if m:
        return float(m.group(1)) / 1000.0
    return None


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
            # Up to two attempts per provider: the second only happens after a
            # 429 that carried a (sane) Retry-After hint.
            for attempt in range(2):
                try:
                    text = await provider.complete(
                        system, user, temperature, max_tokens
                    )
                    if text:
                        return text, provider.name
                    last_exc = RuntimeError(
                        f"{provider.name} returned empty text"
                    )
                    break  # empty response -> rotate
                except Exception as exc:  # noqa: BLE001 - we classify below
                    last_exc = exc
                    if _is_quota_error(exc):
                        retry_after = _retry_after_seconds(exc)
                        if (
                            attempt == 0
                            and retry_after is not None
                            and retry_after <= MAX_RETRY_AFTER_SECONDS
                        ):
                            log.warning(
                                "Provider %s 429; waiting %.1fs then retrying "
                                "once before rotating.",
                                provider.name,
                                retry_after,
                            )
                            await asyncio.sleep(retry_after)
                            continue  # retry the SAME provider once
                        log.warning(
                            "Provider %s hit quota/limit, rotating to next: %s",
                            provider.name,
                            exc,
                        )
                        break
                    log.warning(
                        "Provider %s failed (%s), rotating to next.",
                        provider.name,
                        exc,
                    )
                    break

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
