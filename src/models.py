"""Shared domain models used across the pipeline."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass
class NewsItem:
    """A single news item fetched from a source, before/after processing."""

    source_id: str            # catalog id of the source, e.g. "coindesk"
    source_name: str          # human-readable, e.g. "CoinDesk"
    source_kind: str          # "rss" | "youtube" | "reddit" | "telegram"
    title: str
    link: str
    summary: str = ""
    published: Optional[datetime] = None
    # Whether the source is an official/primary outlet (regulator, exchange,
    # company blog). Drives the "Официально" label and editor proofread.
    official: bool = False
    # Relative importance 0..100 used for prioritisation when near AI limits.
    impact: int = 0
    guid: Optional[str] = None

    @property
    def uid(self) -> str:
        """Stable unique id for deduplication of the *exact* same item."""
        basis = self.guid or self.link or f"{self.source_id}:{self.title}"
        return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:32]

    @property
    def dedup_key(self) -> str:
        """Fuzzy key to detect the same story across different sources.

        Normalises the title to lowercase alphanumeric tokens so that
        "Bitcoin Hits $100K" and "bitcoin hits $100k!!!" collapse together.
        """
        text = self.title.lower()
        text = re.sub(r"[^a-z0-9а-яё ]+", " ", text)
        tokens = [t for t in text.split() if len(t) > 2]
        # Use the most significant tokens (sorted) to be order-insensitive.
        significant = sorted(set(tokens))[:12]
        basis = " ".join(significant)
        return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:24]


@dataclass
class Post:
    """A rendered post ready to be published to Telegram."""

    item: NewsItem
    body: str                     # AI-written substance (Russian)
    official: bool
    provider_used: str
    editor_used: bool = False
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
