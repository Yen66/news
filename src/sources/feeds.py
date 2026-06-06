"""Fetch news items from sources.

RSS / YouTube / Reddit are all RSS/Atom and parsed with feedparser. Public
Telegram channels are scraped from their public web preview (t.me/s/<channel>)
with BeautifulSoup. All network I/O is async via aiohttp; blocking parsers
run in a thread executor so the event loop is never blocked.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from time import mktime
from typing import List, Optional

import aiohttp

from ..models import NewsItem
from .catalog import Source

log = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (compatible; NewsBot/0.1; +https://github.com/yen66/news)"
)


def _struct_to_dt(struct_time) -> Optional[datetime]:
    if not struct_time:
        return None
    try:
        return datetime.fromtimestamp(mktime(struct_time), tz=timezone.utc)
    except Exception:  # pragma: no cover - defensive
        return None


def _parse_rss(text: str, source: Source) -> List[NewsItem]:
    import feedparser  # imported lazily; heavy module

    parsed = feedparser.parse(text)
    items: List[NewsItem] = []
    for entry in parsed.entries:
        title = (entry.get("title") or "").strip()
        link = (entry.get("link") or "").strip()
        if not title or not link:
            continue
        summary = (entry.get("summary") or entry.get("description") or "").strip()
        published = _struct_to_dt(
            entry.get("published_parsed") or entry.get("updated_parsed")
        )
        guid = entry.get("id") or entry.get("guid") or link
        items.append(
            NewsItem(
                source_id=source.id,
                source_name=source.name,
                source_kind=source.kind,
                title=title,
                link=link,
                summary=summary,
                published=published,
                official=source.official,
                impact=source.base_impact,
                guid=guid,
            )
        )
    return items


def _parse_telegram(html: str, source: Source) -> List[NewsItem]:
    """Parse a public t.me/s/<channel> web preview page."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    items: List[NewsItem] = []
    for msg in soup.select(".tgme_widget_message"):
        text_el = msg.select_one(".tgme_widget_message_text")
        if not text_el:
            continue
        text = text_el.get_text(" ", strip=True)
        if not text:
            continue
        link_el = msg.select_one("a.tgme_widget_message_date")
        link = link_el["href"] if link_el and link_el.has_attr("href") else ""
        data_post = msg.get("data-post", "")
        title = text.split("\n")[0][:160]
        items.append(
            NewsItem(
                source_id=source.id,
                source_name=source.name,
                source_kind=source.kind,
                title=title,
                link=link,
                summary=text,
                published=None,
                official=source.official,
                impact=source.base_impact,
                guid=data_post or link or title,
            )
        )
    return items


class FeedFetcher:
    def __init__(self, timeout: int = 20) -> None:
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self) -> "FeedFetcher":
        await self.start()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.aclose()

    async def start(self) -> None:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=self._timeout,
                headers={"User-Agent": _USER_AGENT},
            )

    async def aclose(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    def _url_for(self, source: Source) -> str:
        if source.kind == "telegram":
            return f"https://t.me/s/{source.url}"
        return source.url

    async def fetch_source(self, source: Source) -> List[NewsItem]:
        await self.start()
        assert self._session is not None
        url = self._url_for(source)
        try:
            async with self._session.get(url) as resp:
                if resp.status != 200:
                    log.warning(
                        "Source %s returned HTTP %s", source.id, resp.status
                    )
                    return []
                text = await resp.text()
        except Exception as exc:  # noqa: BLE001 - network errors are expected
            log.warning("Failed to fetch source %s: %s", source.id, exc)
            return []

        loop = asyncio.get_running_loop()
        try:
            if source.kind == "telegram":
                return await loop.run_in_executor(
                    None, _parse_telegram, text, source
                )
            return await loop.run_in_executor(None, _parse_rss, text, source)
        except Exception as exc:  # noqa: BLE001 - parser robustness
            log.warning("Failed to parse source %s: %s", source.id, exc)
            return []

    async def fetch_all(self, sources: List[Source]) -> List[NewsItem]:
        results = await asyncio.gather(
            *(self.fetch_source(s) for s in sources),
            return_exceptions=True,
        )
        items: List[NewsItem] = []
        for res in results:
            if isinstance(res, Exception):
                log.warning("Source fetch raised: %s", res)
                continue
            items.extend(res)
        return items
