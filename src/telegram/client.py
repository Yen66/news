"""Minimal async Telegram Bot API client.

Only what we need: send a message to the channel and send an alert to the
admin. We talk to the HTTP Bot API directly via aiohttp (no heavy library),
which keeps the dependency footprint tiny and free-hosting friendly.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

import aiohttp

log = logging.getLogger(__name__)

_API = "https://api.telegram.org/bot{token}/{method}"
_MAX_LEN = 4096  # Telegram message hard limit


class TelegramClient:
    def __init__(
        self,
        bot_token: str,
        channel_id: str,
        admin_id: str = "",
        *,
        dry_run: bool = False,
        timeout: int = 20,
    ) -> None:
        self._token = bot_token
        self._channel_id = channel_id
        self._admin_id = admin_id
        self._dry_run = dry_run
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._session: Optional[aiohttp.ClientSession] = None

    async def start(self) -> None:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self._timeout)

    async def aclose(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def _send(self, chat_id: str, text: str) -> bool:
        if self._dry_run:
            log.info("[DRY_RUN] -> %s:\n%s", chat_id, text)
            return True
        await self.start()
        assert self._session is not None
        url = _API.format(token=self._token, method="sendMessage")
        payload = {
            "chat_id": chat_id,
            "text": text[:_MAX_LEN],
            "disable_web_page_preview": False,
        }
        # Small retry loop for transient errors / 429.
        for attempt in range(3):
            try:
                async with self._session.post(url, json=payload) as resp:
                    if resp.status == 200:
                        return True
                    body = await resp.text()
                    if resp.status == 429:
                        retry_after = 1 + attempt * 2
                        log.warning("Telegram 429, retrying in %ss", retry_after)
                        await asyncio.sleep(retry_after)
                        continue
                    hint = ""
                    if resp.status in (401, 404):
                        hint = (
                            " (check BOT_TOKEN — a 404/401 here usually means "
                            "the token is empty or wrong)"
                        )
                    elif resp.status == 400 and "chat not found" in body.lower():
                        hint = (
                            " (check CHANNEL_ID, e.g. @CMW_News, and that the "
                            "bot is an admin of that channel)"
                        )
                    log.error(
                        "Telegram sendMessage failed (%s): %s%s",
                        resp.status,
                        body,
                        hint,
                    )
                    return False
            except Exception as exc:  # noqa: BLE001 - network resilience
                log.warning("Telegram send error (attempt %s): %s", attempt, exc)
                await asyncio.sleep(1 + attempt * 2)
        return False

    async def publish(self, text: str) -> bool:
        """Publish a post to the channel."""
        return await self._send(self._channel_id, text)

    async def alert_admin(self, text: str) -> bool:
        """Send an operational alert to the admin (errors, lifecycle)."""
        if not self._admin_id:
            log.warning("No ADMIN_ID set; alert dropped: %s", text)
            return False
        return await self._send(self._admin_id, f"[NewsBot] {text}")
