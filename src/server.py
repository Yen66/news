"""aiohttp web server exposing / and /health for keep-alive pings.

Render's free web service sleeps without traffic; UptimeRobot pings /health
every few minutes to keep it awake. The server also reports basic liveness
of the background polling task.
"""
from __future__ import annotations

import time
from typing import Callable

from aiohttp import web


def build_app(status_provider: Callable[[], dict]) -> web.Application:
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

    app = web.Application()
    app.router.add_get("/", root)
    app.router.add_get("/health", health)
    return app
