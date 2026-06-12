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
import inspect
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from ..models import NewsItem, Post
from .factory import AIClient

log = logging.getLogger(__name__)


class MalformedPostError(Exception):
    """Raised when the AI-written body fails deterministic quality validation
    (gibberish / token salad / placeholder / too short). The processor catches
    it, skips publishing, and does NOT mark the item seen (Phase 6)."""


# How fresh a story must be for the ⚡️ breaking prefix.
BREAKING_WINDOW = timedelta(hours=2)

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
    r"^\s*(ПРЕФИКС|ТЕКСТ|ТИКЕРЫ|ЗАГОЛОВОК|ВЛИЯНИЕ|АКТИВЫ)\s*[:\-—]\s*(.*?)\s*$",
    re.IGNORECASE,
)

_WRITER_SYSTEM = (
    "Ты — финансовый журналист срочных новостей в стиле Bloomberg breaking "
    "news. Пиши на русском: резко, уверенно, по делу, с лёгким ощущением "
    "срочности. Это живая новость, а не отчёт аналитика и не справка из "
    "Википедии.\n\n"
    "Правила:\n"
    "- НЕ пиши заголовок. Начинай сразу с ключевого факта.\n"
    "- Пиши как телеграфный репортёр (wire reporter), а не как аналитик.\n"
    "- КАЖДОЕ предложение обязано содержать конкретный факт: число, имя, дату "
    "или цену. Безжалостно вырезай предложения с общими рассуждениями без "
    "конкретики. Плохо: «Инвесторам необходимо пересмотреть свои стратегии». "
    "Хорошо: «Следующий уровень поддержки BTC — $55 000».\n"
    "- Первое предложение обязательно содержит конкретное число или цитату.\n"
    "- Максимум 3 предложения. Активный залог, цифры в начале.\n"
    "- Цитаты влиятельных людей оформляй строго так: "
    "Имя (Должность): «цитата».\n"
    "- Только русский язык; латиница допустима лишь для тикеров и имён "
    "(BTC, ETH, COIN, Coinbase). Не используй иероглифы и иные алфавиты.\n"
    "- Запрещены фразы «Суть:», «Оценка:», «Метка:», «Время:», слова-"
    "смягчители «возможно», «вероятно», «может», «могут», «скорее всего», и "
    "любые ссылки или URL.\n"
    "- Не выдумывай факты: опирайся только на заголовок и описание.\n\n"
    "ФОРМАТ ОТВЕТА — ВАЛИДНЫЙ JSON-ОБЪЕКТ С ТРЕМЯ СТРОКОВЫМИ ПОЛЯМИ:\n"
    "{\n"
    "  \"prefix\":  \"<пусто; либо ⚡️ если новость действительно срочная/"
    "прорывная; либо флаг страны (🇺🇸 🇷🇺 🇨🇳 🇪🇺 и т.п.), если это новость о "
    "регулировании или политике конкретной страны>\",\n"
    "  \"text\":    \"<до 3 предложений; начни с числа или цитаты; в каждом "
    "предложении конкретный факт>\",\n"
    "  \"tickers\": \"<строка с тикерами и движением, например "
    "\\\"BTC: $59 215 (↓7,25%) · ETH: $2 890 (↓12,3%)\\\". Если точных цен "
    "нет, покажи проценты или капитализацию в формате тикера, например "
    "\\\"Капитализация: -$390 млрд · BTC ↓7,25%\\\". ↑ для роста, ↓ для "
    "падения. Если в материале нет ни цен, ни процентов, ни капитализации — "
    "пустая строка>\"\n"
    "}\n\n"
    "Примеры.\n\n"
    "Пример 1 (решение ФРС по ставке).\n"
    "Input: \"ФРС снизила ставку на 25 б.п., до 4.5%\"\n"
    "Output: {\"prefix\": \"🇺🇸\", \"text\": \"ФРС снизила ставку на 25 "
    "базисных пунктов до 4.5%. Решение единогласное. Следующее заседание — "
    "18 сентября.\", \"tickers\": \"BTC: $61 200 (↑1.2%) · S&P 500 +0.8%\"}\n\n"
    "Пример 2 (листинг на Coinbase).\n"
    "Input: \"Coinbase добавила торговую пару PEPE/USDT\"\n"
    "Output: {\"prefix\": \"\", \"text\": \"Coinbase листит PEPE/USDT. Торги "
    "начнутся через 2 часа. Объём за последние сутки на споте вырос за $40 "
    "млн.\", \"tickers\": \"\"}\n\n"
    "Выведи ТОЛЬКО JSON-объект, без markdown, без обёрток ``` и без любого "
    "другого текста.\n"
    "Never use Greek letters (λ, μ, π) or backslash commands like \\cdot. "
    "Use only standard punctuation: . , ! ? : ; % $ № and spaces. Always "
    "output valid JSON as shown.\n"
    "Никогда не выдумывай имена и должности. Если в источнике нет имени, "
    "пиши просто \"представитель компании\".\n"
    "Никогда не добавляй дату (год, месяц, день), если её нет в источнике. "
    "В частности, не используй годы до 2026.\n"
    "Никогда не сочиняй прямую цитату. Цитата допустима ТОЛЬКО если её "
    "слова присутствуют в заголовке или описании источника. Если в "
    "источнике нет цитаты — не пиши никаких кавычек.\n"
    "Пустые цитаты типа \"мы рады\", \"хорошие возможности\", "
    "\"захватывающие времена\" должны быть полностью опущены.\n"
    "Не выдумывай числа (цены, проценты, суммы). Если числа нет в источнике, "
    "не генерируй его."
)

_WRITER_TEMPLATE = (
    "Источник: {source_name} ({kind}).\n"
    "Заголовок: {title}\n"
    "Описание: {summary}\n\n"
    "Ответ должен быть валидным JSON-объектом с полями prefix, text, tickers."
)

# Forward-looking variant for UPCOMING speeches / testimonies / hearings.
# Same field contract as _WRITER_SYSTEM (ПРЕФИКС/ТЕКСТ/ТИКЕРЫ) so parsing and
# rendering are reused unchanged — only the framing differs.
_SPEECH_WRITER_SYSTEM = (
    "Ты — финансовый журналист CMW_News. Это анонс ПРЕДСТОЯЩЕГО публичного "
    "выступления (речь, показания, слушания, пресс-конференция) важной для "
    "рынков фигуры. Пиши на русском, по делу, без воды.\n\n"
    "Правила:\n"
    "- Это событие в БУДУЩЕМ, ещё не произошло. Не пиши так, будто оно "
    "случилось.\n"
    "- Первое предложение: кто и когда выступает. Если в материале указано "
    "время — переведи его в московское время (МСК) и укажи: «Сегодня в "
    "HH:MM МСК выступит …» или «Завтра в HH:MM МСК …». Если времени нет — "
    "«Сегодня выступит …» без выдуманного времени.\n"
    "- Второе-третье предложение: на что обратить внимание (темы выступления) "
    "и возможное влияние на крипту и risk-активы (BTC, индексы, доллар, "
    "облигации). Конкретно, без общих фраз.\n"
    "- Максимум 3 предложения. Не выдумывай факты: опирайся только на "
    "заголовок и описание. Не выдумывай время, если его нет.\n"
    "- Только русский язык; латиница лишь для тикеров и имён. Без иероглифов, "
    "без ссылок и URL.\n\n"
    "ФОРМАТ ОТВЕТА — ВАЛИДНЫЙ JSON-ОБЪЕКТ:\n"
    "{\n"
    "  \"prefix\":  \"⚠️\",\n"
    "  \"text\":    \"<до 3 предложений по правилам выше>\",\n"
    "  \"tickers\": \"\"\n"
    "}\n\n"
    "Выведи ТОЛЬКО JSON-объект, без markdown и без любого другого текста.\n"
    "Никогда не выдумывай имена и должности. Если в источнике нет имени, "
    "пиши просто \"представитель компании\".\n"
    "Никогда не добавляй дату (год, месяц, день), если её нет в источнике. "
    "В частности, не используй годы до 2026.\n"
    "Никогда не сочиняй прямую цитату. Цитата допустима ТОЛЬКО если её "
    "слова присутствуют в заголовке или описании источника. Если в "
    "источнике нет цитаты — не пиши никаких кавычек.\n"
    "Пустые цитаты типа \"мы рады\", \"хорошие возможности\", "
    "\"захватывающие времена\" должны быть полностью опущены.\n"
    "Не выдумывай числа (цены, проценты, суммы). Если числа нет в источнике, "
    "не генерируй его."
)

_EDITOR_SYSTEM = (
    "Ты — выпускающий редактор срочных новостей. Сделай текст резче и "
    "увереннее, в стиле Bloomberg breaking news: убери смягчающие слова, "
    "повторы и канцелярит, сохрани все цифры и смысл, максимум 3 предложения. "
    "Только русский язык, без иероглифов и иностранных алфавитов (кроме "
    "тикеров и имён). Верни только финальный текст, без комментариев и без "
    "эмодзи."
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
    ".,!?:;'\"()\\[\\]«»—–\\-%$€£₽₿+/&№*@#°=<>~^|·"  # punctuation/symbols
    "↑↓→"                                  # market direction arrows
    "]"
)

# Phrases that must never appear in the body, stripped defensively in case the
# model ignores the instruction.
_FORBIDDEN_PHRASES = (
    "Суть:",
    "Оценка:",
    "Метка:",
    "Время:",
    "не указана",
    "вероятным последствием является",
    # Echoed field labels — the model occasionally repeats the contract labels
    # in its answer; strip them rather than reject the whole post.
    "ПРЕФИКС:",
    "ТЕКСТ:",
    "ТИКЕРЫ:",
    "ЗАГОЛОВОК:",
    "ВЛИЯНИЕ:",
    "АКТИВЫ:",
)

_URL_RE = re.compile(r"(https?://\S+|www\.\S+|t\.me/\S+)", re.IGNORECASE)

# Allowed prefix emojis: the breaking-news bolt, the upcoming-event warning
# sign, and country flags (two regional-indicator symbols, U+1F1E6–U+1F1FF).
_BOLT = "⚡️"          # event already happened / breaking
_WARN = "⚠️"          # upcoming, scheduled appearance (forward-looking)
_FLAG_RE = re.compile("[\U0001F1E6-\U0001F1FF]{2}")


def sanitize_text(text: str) -> str:
    """Drop non-Russian/Latin/numeric characters (e.g. stray CJK glyphs)."""
    cleaned = _ALLOWED_RE.sub("", text)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    return cleaned.strip()


def _strip_urls(text: str) -> str:
    return _URL_RE.sub("", text)


def _strip_forbidden(text: str) -> str:
    for phrase in _FORBIDDEN_PHRASES:
        text = re.sub(re.escape(phrase), "", text, flags=re.IGNORECASE)
    return re.sub(r"\s{2,}", " ", text).strip()


# A sentence is "concrete" if it carries a number, currency, percent, a quote,
# or a Latin token (ticker/name like BTC, SEC, Coinbase).
_CONCRETE_RE = re.compile(r"[0-9$€£₽₿%]|«|»|[A-Za-z]{2,}")


def _keep_concrete_sentences(text: str) -> str:
    """Drop concept-only filler sentences; always keep the lead sentence."""
    parts = [p for p in re.split(r"(?<=[.!?])\s+", text.strip()) if p.strip()]
    if not parts:
        return text.strip()
    kept = [parts[0]]
    for sentence in parts[1:]:
        if _CONCRETE_RE.search(sentence):
            kept.append(sentence)
    return " ".join(kept).strip()


def _clean_body(raw_text: str) -> str:
    """The deterministic body-cleaning pipeline shared by the renderer and the
    output validator: strip URLs, sanitise scripts, drop forbidden phrases,
    keep only concrete sentences."""
    body = sanitize_text(_strip_urls(raw_text or ""))
    body = _strip_forbidden(body)
    body = _keep_concrete_sentences(body)
    return body


def _clean_artifacts(text: str) -> str:
    # Replace specific corrupted patterns
    text = text.replace('Cλυх', 'Слух')
    text = text.replace('cλυх', 'слух')
    text = text.replace('G00GL', 'GOOGL')
    # Remove backslash commands like \cdot
    text = text.replace(r'\cdot', '·')
    # Remove any remaining backslash followed by a word (e.g., \text)
    text = re.sub(r'\\[a-zA-Z]+', '', text)
    # Remove truncated word fragments like "сокры..." (Cyrillic letters followed by ellipsis)
    text = re.sub(r'\b[а-яёА-ЯЁ]+\·{3,}', '', text)
    # Clean up any double spaces created by removals
    text = re.sub(r' {2,}', ' ', text)
    return text.strip()


# --- Anti-hallucination cleaners ------------------------------------------
def _clean_made_up_names(body: str, item: NewsItem) -> str:
    import re
    # Match both Cyrillic and Latin names, optional patronymic, then (Title): or Title:
    pattern = r'([А-Я][а-я]+(?:\s+[А-Я][а-я]+)?|[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s*(?:\([^)]+\))?\s*:'
    source_text = f"{item.title} {item.summary}"

    def replacer(match):
        name = match.group(1).strip()
        # simple word-boundary check
        if name not in source_text and not any(name in part for part in source_text.split()):
            return 'представитель компании '
        return match.group(0)

    return re.sub(pattern, replacer, body)


def _filter_quote(body: str, item: NewsItem) -> str:
    import re
    from ..models import _COIN_ALIASES
    stop_words = ['рады', 'хорошие', 'интерес', 'возможности', 'уверены',
                  'продолжим', 'надеемся', 'важно', 'работаем', 'развиваемся']
    fact_words = ['млн', 'млрд', 'процент', 'доллар', 'цена', 'выручка', 'инвестици',
                  'миллион', 'миллиард', 'биткоин', 'эфириум', 'токен', 'крипт']
    # Match balanced quotes: «...», "..." (but not single quotes)
    quote_pattern = re.compile(r'([«"])(.*?)([»"])', re.DOTALL)

    # Task 1.3 — quote-grounding helper. Significant tokens (4+ letters) of
    # the source title+summary, with crypto/asset aliases normalised so
    # "Bitcoin" / "биткоин" / "BTC" all map to the same canonical token.
    # Letters allowed across Cyrillic and Latin so RU body and EN source
    # share a comparison alphabet through aliasing.
    _CYR_TO_CANONICAL = {
        "биткоин": "btc", "биткоина": "btc", "биткоину": "btc",
        "биткоине": "btc", "биткоином": "btc",
        "эфир": "eth", "эфира": "eth", "эфире": "eth", "эфириум": "eth",
        "эфириума": "eth",
        "солана": "sol", "соланы": "sol",
        "крипто": "crypto", "криптовалют": "crypto", "криптовалюты": "crypto",
        "криптовалюта": "crypto",
        "доллар": "usd", "доллара": "usd", "долларов": "usd",
    }

    def _ground_tokens(text):
        words = re.findall(r"[a-zа-яё]{4,}", text.lower())
        out = set()
        for w in words:
            if w in _COIN_ALIASES:
                out.add(_COIN_ALIASES[w])
            elif w in _CYR_TO_CANONICAL:
                out.add(_CYR_TO_CANONICAL[w])
            else:
                out.add(w)
        return out

    source_tokens = _ground_tokens(f"{item.title} {item.summary}")

    def should_remove(q):
        if len(q) < 15:
            return True
        has_stop = any(sw in q.lower() for sw in stop_words)
        has_digit = bool(re.search(r'\d', q))
        has_fact = any(fw in q.lower() for fw in fact_words)
        # Existing rule: generic stop-word-laden quote with no digit/fact.
        if has_stop and not (has_digit or has_fact):
            return True
        # Task 1.3 grounding rule: an invented quote whose significant words
        # are mostly absent from the source is dropped. ≥40% overlap keeps
        # quotes that lift real source content; lower means fabrication.
        q_tokens = _ground_tokens(q)
        if q_tokens and source_tokens:
            overlap = len(q_tokens & source_tokens) / len(q_tokens)
            if overlap < 0.40:
                return True
        return False

    new_body = body
    for m in quote_pattern.finditer(body):
        full, content = m.group(0), m.group(2)
        if should_remove(content):
            new_body = new_body.replace(full, '', 1)
            # Remove trailing dash/comma/colon before quote
            new_body = re.sub(r'\s*[-–:,]\s*$', '', new_body)
    return new_body.strip()


# --- Task 1.3 — strip invented past years ---------------------------------
_YEAR_4D_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")


def _strip_invalid_years(body: str, item: NewsItem) -> str:
    """Drop sentences carrying a past year (<current UTC year) that is NOT
    present in item.title + item.summary. Years from the source and the
    current year are kept untouched.
    """
    current_year = datetime.now(timezone.utc).year
    source_years = set(_YEAR_4D_RE.findall(f"{item.title} {item.summary}"))
    parts = re.split(r'(?<=[.!?])\s+', body.strip())
    kept = []
    for sentence in parts:
        if not sentence.strip():
            continue
        years = _YEAR_4D_RE.findall(sentence)
        invented_past = [
            y for y in years
            if int(y) < current_year and y not in source_years
        ]
        if invented_past:
            continue  # drop the whole sentence
        kept.append(sentence)
    return " ".join(kept).strip()


def _validate_numbers(body: str, item: NewsItem) -> str:
    import re
    # If body contains "ТИКЕРЫ:" line, split and only process non-ticker parts
    lines = body.split('\n')
    non_ticker_lines = []
    ticker_line = ''
    for line in lines:
        if line.startswith('ТИКЕРЫ:'):
            ticker_line = line
        else:
            non_ticker_lines.append(line)
    source_text = f"{item.title} {item.summary}"

    def _normalize(txt):
        # Strip space / NBSP thousand separators between digits.
        txt = re.sub(r'(?<=\d)[\s ]+(?=\d)', '', txt)
        # Comma as a THOUSAND separator: a comma immediately followed by
        # exactly three digits that are not themselves followed by another
        # digit ("70,000", "1,234,567"). Applied before the decimal rule.
        txt = re.sub(r'(?<=\d),(?=\d{3}(?:\D|$))', '', txt)
        # Remaining comma before 1-2 digits is a DECIMAL comma ("7,25").
        txt = re.sub(r'(\d+),(\d{1,2})(?!\d)', r'\1.\2', txt)
        return txt

    def extract_numbers(txt):
        return [float(x) for x in re.findall(r'\d+(?:\.\d+)?', _normalize(txt))]

    source_nums = extract_numbers(source_text)

    def is_valid(num_str):
        nstr = _normalize(num_str)
        try:
            val = float(re.findall(r'\d+(?:\.\d+)?', nstr)[0])
        except (IndexError, ValueError):
            return True
        if not source_nums:
            # Source carries no numbers, so any number in the body is invented.
            return False
        return any(abs(val - src) / (src + 1e-9) <= 0.05 for src in source_nums)

    num_pattern = re.compile(
        r'(?:\$|€|£)?\s*(\d[\d\s,.]*)\s*'
        r'(?:%|млн|млрд|million|billion|процент|percent)?'
    )

    def replace_in_line(line):
        def repl(m):
            num_part = m.group(1)
            if num_part and not is_valid(num_part):
                full = m.group(0)
                # Task 1.2 (defense in depth): preserve leading/trailing
                # whitespace from the original match so the replacement does
                # not glue to adjacent characters when the regex's optional
                # \s* on either side ate the surrounding spaces.
                leading = re.match(r'\s*', full).group(0)
                trailing = ''
                tail_match = re.search(r'\s*$', full)
                if tail_match:
                    trailing = tail_match.group(0)
                # Ensure at least one space on each side regardless of what
                # the match captured (the integrity gate will reject anyway,
                # but defense in depth keeps a leaked artifact readable).
                lead = leading if leading else ' '
                trail = trailing if trailing else ' '
                return f"{lead}[сумма не указана]{trail}"
            return m.group(0)
        out = num_pattern.sub(repl, line)
        # Collapse any double spaces introduced by the padding above.
        return re.sub(r' {2,}', ' ', out)

    new_non_ticker = [replace_in_line(line) for line in non_ticker_lines]
    result = '\n'.join(new_non_ticker)
    if ticker_line:
        result += '\n' + ticker_line
    return result


# --- Task 1.2: residual-artifact integrity gate --------------------------
# A rendered body that still carries any of these markers is a leaked
# anti-hallucination placeholder. The post must NOT ship: PostWriter.write
# raises MalformedPostError so the processor drops it quietly (no publish,
# no mark-seen, no admin alert).
_RESIDUAL_ARTIFACT_MARKERS = ("[сумма не указана]", "нет цитаты")
# A "dangling" представитель компании = the phrase with no quote («/")
# anywhere afterward in the body (the _clean_made_up_names replacement
# without a paired quotation that would have made it a real attribution).
_DANGLING_REPRESENTATIVE_RE = re.compile(
    r"представитель\s+компании", re.IGNORECASE
)


def _has_residual_artifact(body: str) -> bool:
    if any(marker in body for marker in _RESIDUAL_ARTIFACT_MARKERS):
        return True
    rep_match = _DANGLING_REPRESENTATIVE_RE.search(body)
    if rep_match:
        # Dangling only if there is no Russian-style typographic quote
        # mark anywhere after the rep phrase. ASCII " is excluded — it
        # collides with the HTML <a href="..."> footer.
        tail = body[rep_match.end():]
        if not re.search(r"[«»„“”]", tail):
            return True
    return False


# Substrings that betray a model error / placeholder (echoed field labels are
# stripped by _clean_body, not rejected here).
_PLACEHOLDER_MARKERS = (
    "lorem ipsum", "as an ai", "as a language model", "as an language model",
    "i cannot", "i'm sorry", "i am sorry", "извините, но", "не могу",
    "placeholder", "вставьте", "вставь сюда", "ваш текст", "your text here",
    "<вставьте", "[вставьте",
)
_WORD_RE = re.compile(r"[0-9A-Za-zЀ-ӿԀ-ԯ]+")


def _validate_body(text: str) -> tuple[bool, str]:
    """Return ``(ok, reason)``. ``ok=False`` => the body is malformed and must
    NOT be published. Conservative by design: it catches the production
    failure classes (token salad like ``Суротмасвород``, two-word fragments
    like ``О предложений``, echoed labels, repeated tokens) without rejecting
    legitimate terse one-line posts (e.g. ``Рынок вырос на 3%``)."""
    t = (text or "").strip()
    if not t:
        return False, "empty"
    low = t.lower()
    for marker in _PLACEHOLDER_MARKERS:
        if marker in low:
            return False, f"placeholder:{marker!r}"
    words = _WORD_RE.findall(t)
    # Single concatenated token ("Суротмасвород") or a 2-word fragment
    # ("О предложений") — not a real sentence.
    if len(words) < 3:
        return False, f"too_few_words:{len(words)}"
    # Three identical tokens in a row => degenerate / looping output.
    lowered = [w.lower() for w in words]
    for i in range(len(lowered) - 2):
        if lowered[i] == lowered[i + 1] == lowered[i + 2]:
            return False, "repeated_token"
    return True, ""


def _is_recent(item: NewsItem, window: timedelta = BREAKING_WINDOW) -> bool:
    """True if the article was published within ``window`` (default 2h)."""
    pub = item.published
    if pub is None:
        return False
    if pub.tzinfo is None:
        pub = pub.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - pub <= window


def _clean_prefix(raw: str) -> str:
    """Keep only an allowed prefix: the ⚡️ bolt, the ⚠️ warning sign, or a
    single country flag."""
    if not raw:
        return ""
    flag = _FLAG_RE.search(raw)
    if flag:
        return flag.group(0)
    if "⚠" in raw:
        return _WARN
    if "⚡" in raw:
        return _BOLT
    return ""


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


# --- Per-article credibility detection ------------------------------------
# Hedging / rumor language => "◎ Слух" even from an established outlet.
_RUMOR_PHRASES = (
    "по данным источников", "по слухам", "по информации источников",
    "не подтверж", "reportedly", "sources say", "according to sources",
    "unconfirmed", "rumor", "rumour", "allegedly", "expected to",
    "is considering", "could", "is in talks", "is weighing", "is mulling",
    "is exploring",
)
# Modal hedges matched case-SENSITIVE as whole words so the month "May" or a
# capitalised sentence start does not trigger a false "rumor".
_RUMOR_WORD_RE = re.compile(r"\b(may|might)\b")

# Confirmed-action language => "◉ Официально" even from an unknown outlet.
_OFFICIAL_PHRASES = (
    "press release", "official statement", "announced", "has announced",
    "confirmed", "approved", "signed into law", "regulatory filing",
    "filed with", "sec filing", "files for", "ruling", "passed", "enacted",
    "officially", "launched", "launches", "issued", "ratified",
    "пресс-релиз", "официально", "подтверд", "одобрил", "подписал закон",
)


def has_rumor_language(item: NewsItem) -> bool:
    text = f"{item.title} {item.summary}"
    low = text.lower()
    if any(p in low for p in _RUMOR_PHRASES):
        return True
    return bool(_RUMOR_WORD_RE.search(text))


def has_official_language(item: NewsItem) -> bool:
    low = f"{item.title} {item.summary}".lower()
    return any(p in low for p in _OFFICIAL_PHRASES)


def credibility_label(item: NewsItem) -> str:
    """Per-article credibility.

    Precedence:
    1. Hedging/rumor language -> Слух (even for established outlets).
    2. Confirmed-action language OR established outlet -> Официально.
    3. Otherwise -> Слух.
    """
    if has_rumor_language(item):
        return LABEL_RUMOR
    if has_official_language(item) or is_established_source(item):
        return LABEL_OFFICIAL
    return LABEL_RUMOR


def is_official_post(item: NewsItem) -> bool:
    return credibility_label(item) == LABEL_OFFICIAL


# JSON-first parsing. The model is instructed (and the API call asks it via
# response_format=json_object) to return ``{"prefix": ..., "text": ...,
# "tickers": ...}``. JSON keys are normalised to the legacy uppercase Cyrillic
# names so the renderer and the rest of the pipeline see one shape regardless
# of which path produced the dict.
_JSON_KEY_MAP = {"prefix": "ПРЕФИКС", "text": "ТЕКСТ", "tickers": "ТИКЕРЫ"}
_CODE_FENCE_RE = re.compile(
    r"\A\s*```(?:json)?\s*\n?|\n?\s*```\s*\Z", re.IGNORECASE
)


def truncate_at_sentence(text: str, max_chars: int = 1500) -> str:
    """Truncate ``text`` at the last full stop / exclamation / question mark
    that falls within ``max_chars``. If no such boundary exists, hard-slice and
    append ``"..."``. Returns ``""`` for empty / None input.
    """
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    head = text[:max_chars]
    last_boundary = max(head.rfind("."), head.rfind("!"), head.rfind("?"))
    if last_boundary >= 0:
        return head[: last_boundary + 1].rstrip()
    return head.rstrip() + "..."


def _parse_fields(raw: str) -> dict[str, str]:
    """Parse the model output into the canonical field dict.

    Prefers a JSON object with keys ``prefix`` / ``text`` / ``tickers`` and
    falls back to the legacy labelled-line regex on JSON failure (logged).
    Returned keys are the canonical uppercase Cyrillic names so the renderer
    sees one shape regardless of source.
    """
    stripped = (raw or "").strip()
    # Tolerate a markdown code fence even though we ask the model not to use one.
    if stripped.startswith("```"):
        stripped = _CODE_FENCE_RE.sub("", stripped).strip()

    try:
        data = json.loads(stripped)
    except ValueError as exc:
        # json.JSONDecodeError is a subclass of ValueError.
        log.warning(
            "JSON parse failed (%s); falling back to legacy parser. "
            "First 120 chars: %r",
            exc, stripped[:120],
        )
        return _parse_legacy_fields(raw)

    if not isinstance(data, dict):
        log.warning(
            "Model returned JSON %s, expected object; falling back to "
            "legacy parser.",
            type(data).__name__,
        )
        return _parse_legacy_fields(raw)

    fields: dict[str, str] = {}
    for json_key, canonical in _JSON_KEY_MAP.items():
        val = data.get(json_key)
        if val is None:
            continue
        fields[canonical] = str(val).strip()
    return fields


def _parse_legacy_fields(text: str) -> dict[str, str]:
    """Legacy labelled-line parser (``ПРЕФИКС: ...`` / ``ТЕКСТ: ...`` / etc.).
    Kept as a fallback for non-JSON model responses and exercised by tests
    that pre-date the JSON contract.
    """
    fields: dict[str, str] = {}
    for line in (text or "").splitlines():
        m = _FIELD_RE.match(line)
        if m:
            fields[m.group(1).upper()] = m.group(2).strip()
    return fields


def _render_post(fields: dict[str, str], item: NewsItem) -> str:
    """Assemble the final Telegram-HTML post from parsed fields.

    Layout (no headline):

        [⚡️/flag] <body, up to 3 sentences>

        `TICKER: $price (↓X%) · ...`   (monospace, only if prices present)

        ◉ Официально / ◎ Слух · <Source>

    Every model field is sanitized (stray CJK/foreign glyphs and URLs removed)
    and forbidden phrases are stripped before HTML-escaping.
    """
    e = html.escape

    prefix = _clean_prefix(fields.get("ПРЕФИКС", ""))
    if item.is_upcoming_speech:
        # Forward-looking appearance: always ⚠️, never the ⚡️ breaking bolt.
        prefix = _WARN
    elif prefix == _BOLT and not _is_recent(item):
        # ⚡️ only for news published within the last 2h; flags are not gated.
        prefix = ""

    body = _clean_body(fields.get("ТЕКСТ") or item.summary or item.title or "")
    # Remove model artifacts (Greek look-alikes, backslash commands, truncated
    # fragments) from the rendered text before it reaches Telegram.
    body = _clean_artifacts(body)
    # Anti-hallucination: strip invented names/titles, generic filler quotes
    # and numbers not present in the source.
    body = _clean_made_up_names(body, item)
    body = _filter_quote(body, item)
    body = _validate_numbers(body, item)
    # Task 1.3: strip sentences whose past-year mention is not in the source.
    body = _strip_invalid_years(body, item)

    tickers = sanitize_text(_strip_urls(fields.get("ТИКЕРЫ", "")))

    label = credibility_label(item)
    name = item.source_name or "Источник"
    link = item.link or ""
    if link:
        source_part = f'{label} · <a href="{e(link, quote=True)}">{e(name)}</a>'
    else:
        source_part = f"{label} · {e(name)}"

    # The prefix is a trusted emoji (bolt or flag); the body is HTML-escaped.
    first_line = f"{prefix} {e(body)}".strip() if prefix else e(body)
    lines = [first_line]
    if tickers:
        lines += ["", f"<code>{e(tickers)}</code>"]
    lines += ["", source_part]
    return "\n".join(lines)


def _ai_accepts_response_format(complete_method) -> bool:
    """True if ``complete_method`` accepts a ``response_format`` keyword.

    The production :class:`AIClient.complete` does; legacy test fakes whose
    signature pre-dates the JSON contract do not. Feature-detecting here
    keeps the writer's call site clean without coupling production code to
    a specific fake.
    """
    try:
        params = inspect.signature(complete_method).parameters
    except (TypeError, ValueError):
        return False
    if "response_format" in params:
        return True
    return any(
        p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()
    )


class PostWriter:
    def __init__(self, ai: AIClient, *, enable_editor: bool = True) -> None:
        self._ai = ai
        self._enable_editor = enable_editor
        self._ai_supports_json = _ai_accepts_response_format(ai.complete)

    async def write(self, item: NewsItem) -> Post:
        user = _WRITER_TEMPLATE.format(
            source_name=item.source_name,
            kind=item.source_kind,
            title=item.title,
            summary=truncate_at_sentence(item.summary or "(нет описания)"),
        )

        system = (
            _SPEECH_WRITER_SYSTEM if item.is_upcoming_speech else _WRITER_SYSTEM
        )

        writer_kwargs: dict = {
            "temperature": 0.2,
            "max_tokens": 800,
            "frequency_penalty": 0.3,
            "presence_penalty": 0.2,
        }
        if self._ai_supports_json:
            writer_kwargs["response_format"] = {"type": "json_object"}

        raw, provider = await self._ai.complete(system, user, **writer_kwargs)
        fields = _parse_fields(raw)

        editor_used = False
        official = is_official_post(item)
        # Proofread the main text only for important posts: officially-credible
        # OR high-impact. The editor returns free text, so it does NOT request
        # response_format=json_object.
        important = official or item.impact >= 70
        if self._enable_editor and important and fields.get("ТЕКСТ"):
            try:
                edited, _ = await self._ai.complete(
                    _EDITOR_SYSTEM, fields["ТЕКСТ"], temperature=0.1,
                    max_tokens=400,
                    frequency_penalty=0.3,
                    presence_penalty=0.2,
                )
                if edited.strip():
                    fields["ТЕКСТ"] = edited.strip()
                    editor_used = True
            except Exception as exc:  # noqa: BLE001 - proofread is best-effort
                log.warning("Editor pass failed, using draft: %s", exc)

        # Phase 6: validate the model's own post text (when it returned a
        # parseable ТЕКСТ field) BEFORE rendering/publishing. Token salad,
        # two-word fragments, echoed labels and placeholders are rejected so
        # they can never reach Telegram. (When the model returned no parseable
        # field the renderer falls back to the source title — a separate,
        # already-safe path that is not gibberish.)
        text_field = fields.get("ТЕКСТ")
        if text_field is not None:
            ok, reason = _validate_body(_clean_body(text_field))
            if not ok:
                raise MalformedPostError(
                    f"{reason} | provider={provider} | title={item.title!r}"
                )

        body = _render_post(fields, item)
        # Task 1.2: final integrity gate. A leaked anti-hallucination
        # placeholder means the post's core fact is unverifiable — drop it.
        if _has_residual_artifact(body):
            raise MalformedPostError(
                f"residual_artifact | provider={provider} "
                f"| title={item.title!r}"
            )
        return Post(
            item=item,
            body=body,
            official=official,
            provider_used=provider,
            editor_used=editor_used,
        )
