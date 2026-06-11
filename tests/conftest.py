"""Shared test fixtures and fakes (mocked AI + mocked feeds)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

import pytest

from src.models import NewsItem


_UNSET = object()


def make_item(
    title: str,
    *,
    source_id: str = "test",
    source_name: str = "Test Source",
    kind: str = "rss",
    link: Optional[str] = None,
    summary: str = "",
    official: bool = False,
    impact: int = 40,
    guid: Optional[str] = None,
    published=_UNSET,
    is_upcoming_speech: bool = False,
) -> NewsItem:
    # Default to "now" so the 24h age filter keeps test items, but allow an
    # explicit published=None (distinct from "not passed").
    if published is _UNSET:
        published = datetime.now(timezone.utc)
    return NewsItem(
        source_id=source_id,
        source_name=source_name,
        source_kind=kind,
        title=title,
        link=link if link is not None else f"https://example.com/{abs(hash(title))}",
        summary=summary,
        official=official,
        impact=impact,
        guid=guid,
        published=published,
        is_upcoming_speech=is_upcoming_speech,
    )


class FakeAIClient:
    """Stand-in for src.ai.factory.AIClient.

    Records prompts and returns canned text. Can be told to raise on the
    first N calls to exercise editor-failure / retry paths.
    """

    def __init__(self, reply: str = "Готовый пост о рынке", provider: str = "groq"):
        self.reply = reply
        self.provider = provider
        self.calls: List[tuple[str, str]] = []
        self.fail_times = 0

    @property
    def available(self) -> bool:
        return True

    @property
    def provider_names(self) -> List[str]:
        return [self.provider]

    async def complete(self, system, user, *, temperature=0.4, max_tokens=800,
                       **kwargs):
        # Accept and ignore optional kwargs (e.g. response_format,
        # frequency_penalty, presence_penalty) so the fake stays compatible
        # with the real AIClient.complete signature as it evolves.
        self.calls.append((system, user))
        if self.fail_times > 0:
            self.fail_times -= 1
            raise RuntimeError("forced failure")
        return self.reply, self.provider

    async def aclose(self):
        pass


class FakeTelegram:
    def __init__(self):
        self.published: List[str] = []
        self.alerts: List[str] = []

    async def start(self):
        pass

    async def aclose(self):
        pass

    async def publish(self, text: str) -> bool:
        self.published.append(text)
        return True

    async def alert_admin(self, text: str) -> bool:
        self.alerts.append(text)
        return True


@pytest.fixture
def fake_ai():
    return FakeAIClient()


@pytest.fixture
def fake_telegram():
    return FakeTelegram()
