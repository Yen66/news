"""Turn a NewsItem into a finished Russian-language post.

This is the ONLY place we call the AI in the per-item pipeline:
- one call writes the post (returned as four labelled fields);
- one optional second call (the "editor") proofreads the main text of
  important posts.

The credibility label, the bold headline, the clickable publication link and
the overall HTML layout are deterministic plain code. The post is rendered as
Telegram HTML (sent with parse_mode=HTML).

Output style: a Bloomberg-terminal alert crossed with a sharp analyst —
confident, direct, numbers-first, no hedging, no emoji, Russian.
"""
from __future__ import annotations

import html
import logging
import re
from urllib.parse import urlparse

from ..models import NewsItem, Post
from .factory import AIClient

log = logging.getLogger(__name__)

# Established outlets / authorities -> "Официально". Matched against the source
# name and the link domain (case-insensitive substring). Everything else
# (unknown blogs, social media, aggregators) is labelled "Слух".
ESTABLISHED_OUTLETS = {
    "coindesk", "cointelegraph", "reuters", "bloomberg", "financial times",
    "ft.com", "cnbc", "wsj", "wall street journal", "the block", "theblock",
    "decrypt", "forbes", "marketwatch", "barron", "axios", "associated press",
    "ap news", "apnews", "cnn", "nasdaq.com", "the information",
    # Authorities / regulators
    "sec", "u.s. securities", "securities and exchange", "federal reserve",
    "the fed", "ecb", "european central bank", "imf", "treasury",
    "commodity futures", "cftc",
}

# Credibility marks.
LABEL_OFFICIAL = "◉ Официально"
LABEL_RUMOR = "◎ Слух"

_FIELD_RE = re.compile(
    r"^\s*(ЗАГОЛОВОК|ТЕКСТ|ВЛИЯНИЕ|АКТИВЫ)\s*[:\-—]\s*(.+?)\s*$",
    re.IGNORECASE,
)

_WRITER_SYSTEM = (
    "Ты — финансовый журналист, который пишет срочные новости в стиле "
    "Bloomberg breaking news: резко, уверенно, по делу, с лёгким ощущением "
    "срочности. Это живая новость, а не отчёт аналитика и не справка из "
    "Википедии.\n\n"
    "Правила для поля ТЕКСТ:\n"
    "- Начни с самого драматичного и важного факта, сразу с цифр.\n"
    "- Активный залог, конкретные числа в начале предложения.\n"
    "- Простыми словами объясни, почему это важно именно криптоинвестору.\n"
    "- Максимум 3 предложения.\n"
    "- Только русский язык. Не используй иероглифы и другие иностранные "
    "алфавиты; латиница допустима лишь для тикеров (BTC, ETH, COIN).\n"
    "- Запрещены фразы: «Суть:», «Оценка:», «не указана», «вероятным "
    "последствием является», а также слова-смягчители «возможно», "
    "«вероятно», «может», «могут», «скорее всего».\n"
    "- Не выдумывай факты: опирайся только на заголовок и описание.\n\n"
    "Верни РОВНО четыре строки строго в этом формате, без markdown и без "
    "любого другого текста:\n"
    "ЗАГОЛОВОК: <ёмкий, цепкий заголовок 3-7 слов, без точки в конце>\n"
    "ТЕКСТ: <до 3 предложений в стиле срочной новости, с цифрами>\n"
    "ВЛИЯНИЕ: <высокое|среднее|низкое> <↑ бычье|↓ медвежье|→ нейтральное>\n"
    "АКТИВЫ: <конкретные тикеры/активы через запятую>"
)

_WRITER_TEMPLATE = (
    "Источник: {source_name} ({kind}).\n"
    "Заголовок: {title}\n"
    "Описание: {summary}"
)

_EDITOR_SYSTEM = (
    "Ты — выпускающий редактор срочных новостей. Сделай текст резче и "
    "увереннее, в стиле Bloomberg breaking news: убери смягчающие слова, "
    "повторы и канцелярит, сохрани все цифры и смысл, максимум 3 предложения. "
    "Только русский язык, без иероглифов и иностранных алфавитов (кроме "
    "тикеров). Верни только финальный текст, без комментариев и без эмодзи."
)

# Characters we allow through from the model. Anything else (e.g. Chinese /
# Japanese / Korean glyphs that occasionally leak from multilingual models) is
# stripped before rendering. We keep Cyrillic, Latin, digits, whitespace,
# common punctuation/currency, and the market-direction arrows.
_ALLOWED_RE = re.compile(
    "[^"
    "Ѐ-ӿԀ-ԯ"          # Cyrillic
    "A-Za-z0-9"                            # Latin + digits
    "\\s"                                  # whitespace
    ".,!?:;'\"()\\[\\]«»—–\\-%$€£₽₿+/&№*@#°=<>~^|"   # punctuation/symbols
    "↑↓→"                                  # market direction arrows
    "]"
)

# Phrases that must never appear in the body, stripped defensively in case the
# model ignores the instruction.
_FORBIDDEN_PHRASES = (
    "Суть:",
    "Оценка:",
    "не указана",
    "вероятным последствием является",
)


def sanitize_text(text: str) -> str:
    """Drop non-Russian/Latin/numeric characters (e.g. stray CJK glyphs)."""
    cleaned = _ALLOWED_RE.sub("", text)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    return cleaned.strip()


def _strip_forbidden(text: str) -> str:
    for phrase in _FORBIDDEN_PHRASES:
        text = re.sub(re.escape(phrase), "", text, flags=re.IGNORECASE)
    return re.sub(r"\s{2,}", " ", text).strip()


def _domain(link: str) -> str:
    try:
        return (urlparse(link).netloc or "").lower()
    except Exception:  # pragma: no cover - defensive
        return ""


def is_established_source(item: NewsItem) -> bool:
    """True for known outlets / authorities / .gov domains."""
    if item.official:
        return True
    domain = _domain(item.link)
    haystack = f"{item.source_name.lower()} {domain}"
    if any(name in haystack for name in ESTABLISHED_OUTLETS):
        return True
    if domain.endswith(".gov") or ".gov." in domain:
        return True
    return False


def credibility_label(item: NewsItem) -> str:
    return LABEL_OFFICIAL if is_established_source(item) else LABEL_RUMOR


def _parse_fields(text: str) -> dict[str, str]:
    """Leniently parse the four labelled fields from the model output."""
    fields: dict[str, str] = {}
    for line in text.splitlines():
        m = _FIELD_RE.match(line)
        if m:
            fields[m.group(1).upper()] = m.group(2).strip()
    return fields


def _render_post(fields: dict[str, str], item: NewsItem) -> str:
    """Assemble the final Telegram-HTML post from parsed fields.

    Every model-produced field is sanitized (stray CJK/foreign glyphs removed)
    and the body has any forbidden phrases stripped before HTML-escaping.
    """
    e = html.escape

    headline = sanitize_text(fields.get("ЗАГОЛОВОК") or item.title or "")
    headline = headline.rstrip(".").upper()

    body = sanitize_text(fields.get("ТЕКСТ") or item.summary or item.title or "")
    body = _strip_forbidden(body)
    impact = sanitize_text(fields.get("ВЛИЯНИЕ") or "среднее → нейтральное")
    assets = sanitize_text(fields.get("АКТИВЫ") or "—")

    label = credibility_label(item)
    name = item.source_name or "Источник"
    link = item.link or ""

    if link:
        source_part = f'{label} · <a href="{e(link, quote=True)}">{e(name)}</a>'
    else:
        source_part = f"{label} · {e(name)}"

    lines = [
        f"<b>{e(headline)}</b>",
        "",
        e(body),
        "",
        f"Влияние: {e(impact)}",
        f"Активы: {e(assets)}",
        "",
        source_part,
    ]
    return "\n".join(lines)


class PostWriter:
    def __init__(self, ai: AIClient, *, enable_editor: bool = True) -> None:
        self._ai = ai
        self._enable_editor = enable_editor

    async def write(self, item: NewsItem) -> Post:
        user = _WRITER_TEMPLATE.format(
            source_name=item.source_name,
            kind=item.source_kind,
            title=item.title,
            summary=(item.summary or "(нет описания)")[:1500],
        )

        raw, provider = await self._ai.complete(
            _WRITER_SYSTEM, user, temperature=0.5, max_tokens=400
        )
        fields = _parse_fields(raw)

        editor_used = False
        established = is_established_source(item)
        # Proofread the main text only for important posts: established outlet
        # OR high-impact.
        important = established or item.impact >= 70
        if self._enable_editor and important and fields.get("ТЕКСТ"):
            try:
                edited, _ = await self._ai.complete(
                    _EDITOR_SYSTEM, fields["ТЕКСТ"], temperature=0.2,
                    max_tokens=300,
                )
                if edited.strip():
                    fields["ТЕКСТ"] = edited.strip()
                    editor_used = True
            except Exception as exc:  # noqa: BLE001 - proofread is best-effort
                log.warning("Editor pass failed, using draft: %s", exc)

        body = _render_post(fields, item)
        return Post(
            item=item,
            body=body,
            official=established,
            provider_used=provider,
            editor_used=editor_used,
        )
