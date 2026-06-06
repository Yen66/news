"""Russian-language news Telegram bot.

Layered architecture:
- src.config        runtime configuration loaded from environment variables
- src.ai            multi-provider, OpenAI-compatible AI client + factory
- src.sources       feed catalog and fetchers (RSS, t.me/s)
- src.pipeline      filtering, deduplication, throttled processing queue
- src.telegram      Telegram channel posting and admin alerts
- src.db            repository layer (Postgres via asyncpg, in-memory fallback)
- src.server        aiohttp web server (/ and /health) for keep-alive pings
- src.app           wiring of all components
- src.main          process entrypoint
"""

__version__ = "0.1.0"
