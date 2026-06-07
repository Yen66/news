"""Process entrypoint.

Run with:  python -m src.main
"""
from __future__ import annotations

import asyncio
import logging
import signal

from .app import NewsBotApp
from .config import load_config


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


async def _amain() -> None:
    config = load_config()
    _setup_logging(config.log_level)
    log = logging.getLogger("news.main")

    if not config.telegram.configured:
        log.warning(
            "Telegram is not fully configured (BOT_TOKEN / CHANNEL_ID). "
            "The bot will run but cannot publish."
        )
    if not config.usable_providers:
        log.warning(
            "No usable AI providers configured. Set at least one provider key."
        )

    app = NewsBotApp(config)

    loop = asyncio.get_running_loop()
    stop = asyncio.Event()

    def _request_stop() -> None:
        log.info("Shutdown signal received.")
        stop.set()
        app._stopping.set()  # noqa: SLF001 - intentional internal signal

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _request_stop)
        except NotImplementedError:  # pragma: no cover - e.g. Windows
            pass

    await app.run()


def main() -> None:
    try:
        asyncio.run(_amain())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
