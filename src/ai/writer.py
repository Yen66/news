"""Turn a NewsItem into a finished Russian-language post.

This is the ONLY place we call the AI in the per-item pipeline:
- one call writes the post body;
- one optional second call (the "editor") proofreads important posts.

Everything else (the footer with MSK time + source link, the label) is
deterministic plain code.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from ..models import NewsItem, Post
from .factory import AIClient

log = logging.getLogger(__name__)

# Moscow is UTC+3 (no DST since 2014).
MSK = timezone(timedelta(hours=3))

_WRITER_SYSTEM = (
    "Ты — редактор русскоязычного новостного канала о криптовалютах и "
    "финансовых рынках. Пиши строго на русском языке, без эмодзи, без "
    "хэштегов, без воды и рекламных оборотов. Объясняй суть простыми "
    "словами: что произошло, почему это важно, какова причина и какое "
    "вероятное последствие или проблема. Не выдумывай факты: опирайся "
    "только на предоставленные заголовок и описание. Будь краток: 4-8 "
    "предложений."
)

_WRITER_TEMPLATE = (
    "Источник: {source_name} ({kind}).\n"
    "Тип источника: {origin}.\n"
    "Заголовок: {title}\n"
    "Описание: {summary}\n\n"
    "Напиши пост для канала по следующей структуре (без эмодзи):\n"
    "1) Суть: что произошло, причина и вероятное последствие/проблема.\n"
    "2) Оценка влияния на рынок: рост / падение / нейтрально, и какие "
    "активы это затрагивает.\n"
    "3) Метка достоверности отдельной строкой: либо 'Официально', либо "
    "'Слух / не подтверждено' — выбери на основе типа источника.\n"
    "Не добавляй ссылку и время — их допишет система."
)

_EDITOR_SYSTEM = (
    "Ты — выпускающий редактор. Вычитай текст: исправь грамматику, убери "
    "повторы, рекламные обороты и эмодзи, сохрани смысл и структуру. Верни "
    "только финальный текст без комментариев."
)


def _format_footer(item: NewsItem) -> str:
    when = item.published or datetime.now(timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    msk = when.astimezone(MSK)
    stamp = msk.strftime("%d.%m.%Y %H:%M МСК")
    link = item.link or ""
    return f"\n\nВремя: {stamp}\nИсточник: {link}".rstrip()


def _ensure_label(body: str, official: bool) -> str:
    """Guarantee a credibility label is present even if the model omitted it."""
    lower = body.lower()
    if "официально" in lower or "не подтверждено" in lower or "слух" in lower:
        return body
    label = "Официально" if official else "Слух / не подтверждено"
    return f"{body}\n\n{label}"


class PostWriter:
    def __init__(self, ai: AIClient, *, enable_editor: bool = True) -> None:
        self._ai = ai
        self._enable_editor = enable_editor

    async def write(self, item: NewsItem) -> Post:
        origin = "официальный/первоисточник" if item.official else "вторичный"
        user = _WRITER_TEMPLATE.format(
            source_name=item.source_name,
            kind=item.source_kind,
            origin=origin,
            title=item.title,
            summary=(item.summary or "(нет описания)")[:1500],
        )

        body, provider = await self._ai.complete(
            _WRITER_SYSTEM, user, temperature=0.4, max_tokens=700
        )
        body = _ensure_label(body.strip(), item.official)

        editor_used = False
        # Proofread only important posts: official OR high-impact.
        important = item.official or item.impact >= 70
        if self._enable_editor and important:
            try:
                edited, _ = await self._ai.complete(
                    _EDITOR_SYSTEM, body, temperature=0.2, max_tokens=700
                )
                if edited.strip():
                    body = _ensure_label(edited.strip(), item.official)
                    editor_used = True
            except Exception as exc:  # noqa: BLE001 - proofread is best-effort
                log.warning("Editor pass failed, using draft: %s", exc)

        body = body + _format_footer(item)
        return Post(
            item=item,
            body=body,
            official=item.official,
            provider_used=provider,
            editor_used=editor_used,
        )
