"""aiohttp web server exposing / and /health for keep-alive pings.

Render's free web service sleeps without traffic; UptimeRobot pings /health
every few minutes to keep it awake. The server also reports basic liveness
of the background polling task.
"""
from __future__ import annotations

import time
from typing import Awaitable, Callable, Optional

from aiohttp import web

TestPost = Callable[[], Awaitable[dict]]


def build_app(
    status_provider: Callable[[], dict],
    test_post: Optional[TestPost] = None,
) -> web.Application:
    started = time.time()

    async def root(_request: web.Request) -> web.Response:
        return web.json_response(
            {
                "service": "news-telegram-bot",
                "status": "ok",
                "uptime_seconds": int(time.time() - started),
            }
        )

    async def health(_request: web.Request) -> web.Response:
        status = status_provider()
        healthy = status.get("poller_alive", True)
        return web.json_response(
            {"status": "ok" if healthy else "degraded", **status},
            status=200 if healthy else 503,
        )

    async def test_post_handler(_request: web.Request) -> web.Response:
        if test_post is None:
            return web.json_response(
                {"status": "error", "error": "test-post not available"},
                status=503,
            )
        try:
            result = await test_post()
            ok = result.get("published") is True
            return web.json_response(
                {"status": "ok" if ok else "error", **result},
                status=200 if ok else 500,
            )
        except Exception as exc:  # noqa: BLE001 - report the failure to caller
            return web.json_response(
                {"status": "error", "error": repr(exc)}, status=500
            )

    app = web.Application()
    app.router.add_get("/", root)
    app.router.add_get("/health", health)
    # End-to-end pipeline check: fetch one fresh CoinDesk article, bypass the
    # seen-check, write it with the AI and post it to Telegram.
    app.router.add_get("/test-post", test_post_handler)
    return app
