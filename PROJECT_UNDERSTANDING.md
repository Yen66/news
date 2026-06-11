# PROJECT_UNDERSTANDING.md

> Handoff document for **chat-Claude** (the strategist/reviewer/prompt-author).
> Written by Claude Code on 2026-06-11, verified against the repository at
> commit `843b55b` on branch `main`.
>
> **Purpose of this file:** chat-Claude in a future session will NOT have the
> repo checked out, the conversation history, or this session's context. This
> file is the complete context dump so chat-Claude can plan, review, decompose
> tasks, and write clean prompts for Claude Code (the executor) without
> re-discovering everything from scratch.

---

## 1. What the project is

An **automated Telegram news channel** (`@CMW_News`) covering **cryptocurrency and
macroeconomics**. The goal is to give subscribers the freshest, most important,
**verified** news with no fluff — the channel does the gathering, de-noising, and
interpretation that a trader/investor/analyst would otherwise do by hand.

**Audience:** crypto + macro traders, investors, analysts who need to understand
quickly what is happening. Without the channel they'd have to gather news from
many sources themselves, filter out noise, and interpret it alone.

This framing drives the whole design: every false positive (a forecast, a
technical-analysis piece, a hallucinated name/number) directly breaks the
"verified, no fluff" promise the audience subscribes for. That's why so much of
the codebase is anti-noise and anti-hallucination machinery.

---

## 2. Tech stack & architecture (verified against code)

**Language:** Python 3.11 (`Dockerfile`: `FROM python:3.11-slim`; no `.python-version`).

**Key libraries** (`requirements.txt` / `requirements-dev.txt`):
- `aiohttp` — async web server (`/`, `/health`, `/test-post`), the Telegram
  client, and the feed fetcher. **(Telegram is NOT python-telegram-bot or httpx —
  it's raw aiohttp POSTing to the Bot API.)**
- `openai` (`AsyncOpenAI`) — OpenAI-compatible client used for all providers.
- `feedparser` — RSS/Atom parsing.
- `beautifulsoup4` — parsing `t.me/s/<channel>` web previews (no telegram sources
  enabled right now, but the path exists).
- `asyncpg` — Neon Postgres (tables `sent_news`, `archive`); in-memory fallback
  when `DATABASE_URL` is empty (resets each restart).
- `python-dotenv`, `PyYAML` (pre-event calendar), `tzdata`.
- Dev: `pytest`, `pytest-asyncio`.

**Hosting:** Render free web service (`render.yaml`) + Neon Postgres free tier +
UptimeRobot keep-alive ping to `/health`. Env vars via `.env` locally / Render
dashboard in prod. Budget is **$0** — only free tiers and free LLM endpoints.

**Repo:** https://github.com/Yen66/news (branch policy: commit to `main`).

**Single process, one container** (`src/main.py` → `NewsBotApp` in `src/app.py`):
an aiohttp server (keep-alive) + a **poller** task + a **consumer** task.

### How a news item becomes a post (verified end-to-end)
1. **Fetch** — `src/sources/feeds.py::FeedFetcher` pulls all enabled feeds in
   parallel (`_parse_rss`; also `_parse_telegram` for t.me previews). Cadence:
   `POLL_INTERVAL_SECONDS` (default 30s). Sources live in
   `src/sources/catalog.py` (16 enabled RSS; 4 Reddit disabled).
2. **NewsItem** — dataclass in `src/models.py`. Fields are
   `source_id, source_name, source_kind, title, link, summary, published,
   official, impact, guid, is_upcoming_speech`.
   **Note:** "source" is split into THREE fields, and `NewsItem` is a **dataclass**
   — access with `item.title`, NOT `item.get('title')` (see Gotchas).
3. **Age filter** — `src/app.py::_filter_by_age` drops items >24h
   (`MAX_ARTICLE_AGE_HOURS`), with no `published`, with a naive timezone, or
   future-dated. (This already exists — do not add a second age filter.)
4. **Historical / relevance / impact filtering** (all in `src/pipeline/filters.py`):
   - `is_invalid_noise` — firewall: retrospectives, opinion/analysis phrasing,
     noise URL sections (`/learn/`, `/analysis/`, …), ZeroHedge extra scrutiny.
   - `should_publish` — **event-first gate**: requires a real event
     (`has_real_event`); hard-rejects forecasts (`is_forecast`), technical
     analysis (`is_technical_analysis`), memecoin pumps (`is_memecoin_pump`).
   - `score_impact` (0–100) + `filter_items` — impact floor
     (`MIN_IMPACT_TO_PUBLISH`, default 45), tier-2-only catalyst gate,
     routine-recap reject. Official sources bypass the impact bar.
5. **Dedup (two layers):**
   - `Deduplicator` (`src/pipeline/dedup.py`) — permanent, keyed on
     `item.uid` = sha256(guid ‖ link ‖ `source_id:title`). DB-backed.
   - `StoryDeduplicator` (`src/pipeline/story.py`) — 6h window, keyed on
     `story_key(title)` = normalised numbers + tickers + significant words, with
     event-verb synonyms canonicalised (so "Meta announces X" == "Meta unveils X").
   - **Title alone is NOT a dedup key.**
6. **AI write** — `src/ai/writer.py::PostWriter.write` (the ONLY AI call site):
   - Builds system + user prompt; **demands JSON** `{prefix, text, tickers}`.
   - Uses `AIClient` (`src/ai/factory.py`) which rotates providers on quota/429:
     **Groq → Cerebras → OpenRouter** (Llama-3.3-70B models). Gemini exists in
     code (`gemini-1.5-flash`) but is **disabled by default**.
   - Writer params: `temperature=0.2, max_tokens=800, frequency_penalty=0.3,
     presence_penalty=0.2`, `response_format={"type":"json_object"}`.
   - Optional **editor** pass (only when official OR `impact >= 70`):
     `temperature=0.1, max_tokens=400, frequency_penalty=0.3, presence_penalty=0.2`,
     no `response_format`.
   - Parser: `_parse_fields` tries `json.loads` (tolerates ``` fences), falls
     back to the legacy `ПРЕФИКС:/ТЕКСТ:/ТИКЕРЫ:` line parser on failure (logged).
   - Output validation: `_validate_body` rejects gibberish/too-short/placeholder
     → raises `MalformedPostError` → processor drops it quietly (no publish, no
     mark-seen, no admin alert).
7. **Post-processing in `_render_post`** (in order, on the `body` string):
   - `_clean_artifacts` — fixes Greek look-alikes (`Cλυх`→`Слух`), `\cdot`→`·`,
     strips `\command` and truncated `Cyrillic···` fragments.
   - `_clean_made_up_names` — an attribution whose name isn't in
     `title + summary` → `представитель компании`.
   - `_filter_quote` — removes generic filler quotes (short, or stop-word-laden
     with no digit/fact).
   - `_validate_numbers` — replaces body numbers absent from source (5%
     tolerance) with `[сумма не указана]`; skips the `ТИКЕРЫ:` line. Handles RU
     decimal comma (`7,25`) and thousand separators (NBSP/space and `70,000`).
8. **Publish** — `src/telegram/client.py` POSTs `sendMessage` (HTML, link
   previews off) to the channel. Footer: `◉ Официально` / `◎ Слух` ·
   `<a href="link">Source</a>`. Prefix: `⚡️` only if <2h old; `⚠️` for upcoming
   speeches; country flag any time.
9. **Telemetry** — every AI call logs `provider, model, prompt_tokens,
   completion_tokens, total_tokens, finish_reason, json_mode` (English logs),
   plus a WARNING when `finish_reason == "length"`.

**Other moving parts:** daily AI-call budget (`DAILY_AI_CALL_BUDGET=1000`),
15s spacing between consumer AI calls (`AI_CALL_MIN_INTERVAL_SECONDS`), a
pre-event calendar/scheduler (`src/events/`, disabled by default), and the
`/test-post` endpoint (now gated behind `TEST_POST_SECRET`).

**Tests:** **253 pass** when feedparser-dependent tests are excluded
(`pytest --ignore=tests/test_feeds.py --ignore=tests/test_age_filter.py`).
Those are skipped only because `sgmllib3k` (a feedparser build dep) won't compile
in the sandbox — not a code defect.

---

## 3. Current state (honest)

**Live system with real subscribers (~3), ~10–20 posts/day, fully automated.**

**Done:**
- Full pipeline automation: RSS → filter → AI → post → Telegram.
- Anti-hallucination cleaners (names, empty quotes, fake numbers).
- Provider rotation with fallbacks (Groq → Cerebras → OpenRouter).
- Telemetry (provider/model/tokens/finish_reason).
- 253 tests green.

**In progress:**
- Stabilising post quality (occasional old news or odd numbers still slip).
- Growing audience and post frequency.

**Known issues / friction:**
- **Wrong years (e.g. 2024) despite the prompt ban.** Likely the *model
  hallucinating the year* (Llama training cutoff), NOT stale RSS — `_filter_by_age`
  already rejects >24h and future-dated items before the AI sees them.
  `_validate_numbers` does not catch years (4-digit years legitimately appear in
  real news). Tightening this is a separate, optional task.
- **`_validate_numbers` edge case.** The `$70,000` (EN source) vs `$70 000`
  (RU body) mangling was FIXED in `843b55b` (Option B: thousand/decimal comma
  disambiguation). Remaining caveat: when the source `title+summary` contains NO
  digits, ANY number in the body is treated as invented and dropped — consistent
  with policy, but can strip a good figure if the summary was truncated. Lever to
  relax: only run when `source_nums` is non-empty.
- **No deployment automation** — deploys are manual (fine at current scale).
- **Post quality is the main ongoing goal.**

---

## 4. Role split — how this project is "managed"

Two distinct roles. **Keep them separate.**

- **chat-Claude (regular Claude, in the browser/app)** = strategist. Reads this
  file. Handles architecture, planning, task decomposition, reviews, and — most
  importantly — **writes the prompts that get handed to Claude Code.** Does the
  thinking.

- **Claude Code (the executor, e.g. this session)** = reliable coder. Given a
  clear, ready-made prompt: writes code, runs tests, commits, pushes, reports.
  **Minimum questions, maximum action.** Does the doing.

### Executor-mode contract (what Claude Code does by default)
- Implements the task, runs the relevant tests, and reports results faithfully
  (including failures — never claims green when red).
- Commits with a descriptive message. **Pushes to `main` when the task says to or
  clearly implies "ship it"; otherwise commits locally and asks.**
- **Stops and asks** when: tests fail in a way the prompt didn't anticipate, the
  change is destructive (force-push, history rewrite, file/table deletion), the
  spec is internally contradictory, or the change is materially larger than the
  prompt implied.
- Respects stated file scope. If a task says "only modify X" but X can't work
  without touching Y, it reports the conflict rather than silently editing Y.

### How chat-Claude should write prompts for Claude Code (rubric)
A prompt lands cleanly when it states:
1. **Scope** — exactly which files may change ("only `src/ai/writer.py`").
2. **Concrete change** — the function/behaviour, ideally with the exact code or a
   precise description; reference real symbols (they're in §2).
3. **Tests** — what to run and what "pass" means (`pytest -k "not feedparser"`).
4. **Ship instruction** — explicitly "commit and push to main" OR "commit only,
   don't push." Don't leave it implicit.
5. **Guardrails** — "don't refactor unrelated code," "keep Russian in bot output,
   English in logs," "don't revert commit <hash>."
6. **Reality checks** — `NewsItem` is a dataclass (no `.get()`); the channel is
   Russian-only (replacements must be Russian); `_filter_by_age` already exists.

### Gotchas that have actually bitten prompts in this repo
- `NewsItem` is a **dataclass** — `item.get('x')` raises `AttributeError`. Use
  `item.title` / `item.summary` / `item.link` / `item.published`.
- `_render_post`'s local variable is **`body`**, parameter is **`item`** (not
  `text` / `news_item`).
- **Russian-only output** — never inject English placeholders into posts
  (`sanitize_text` whitelist + the writer's language rule will fight you).
- **Old-news filtering already exists** in `app.py::_filter_by_age` and is
  UTC-correct (`feeds.py::_struct_to_dt` uses `calendar.timegm`, not
  `time.mktime` — the latter re-introduces a timezone bug fixed in `50dc72f`).
- `FakeAIClient.complete` (in `tests/conftest.py`) takes `**kwargs` so new
  optional AI params don't break the ~250 tests.
- Feedparser tests fail in the sandbox for environmental reasons only — exclude
  them, don't "fix" them.

---

## 5. Access, capabilities & security boundary (for chat-Claude's future sessions)

**chat-Claude can rely on:**
- **Public GitHub repo:** https://github.com/Yen66/news — readable via web fetch /
  raw links.
- **Acting with provided keys/tokens** — the user trusts chat-Claude to use API
  keys to perform real actions: update GitHub (commit/push/PR — **only when the
  user explicitly asks**), read live Telegram channel posts via the Bot API
  (token provided by the user), analyse logs, write/review code.
- **On request, the user will provide:** fresh error logs, specific code
  fragments, test outputs, any other data needed.

**chat-Claude must NOT (and should not try to):**
- Access the server or database directly — the user supplies extracts if needed.
- Publish keys online or share them with anyone.

### 🔒 CRITICAL SECURITY RULE — non-negotiable
**Never expose, copy, paste, quote, echo, or otherwise output any API key or
secret token — in any response, under any pretext: not in code, not in
explanations, not in logs, not in error messages.**

- Secrets may be **used** internally (to authenticate a request) but **never
  revealed**.
- The only exception: the user themselves typing a key into the official Claude
  site/app from their own account — that's the user's responsibility.
- **When in doubt, ask the user to paste the key directly into the environment /
  a secure variable, rather than asking Claude to echo it.**
- Operational reality that makes this free: Claude never *needs* to output a
  secret to do the work — keys live in env vars (or a PAT pasted transiently into
  a git remote URL and scrubbed right after). Treat the rule as an absolute.

**Never commit to the repo:** `BOT_TOKEN`, `DATABASE_URL`, any `*_API_KEY`,
`TEST_POST_SECRET`, subscriber IDs, or `ADMIN_ID`. `.env` is git-ignored; keep it
that way. `.env.example` documents variable *names* only — never real values.

---

## Summary (TL;DR for a cold start)

`@CMW_News` is a **live, fully-automated Russian-language Telegram channel** for
crypto + macro traders, running on free tiers (Render + Neon + free LLM
endpoints), publishing ~10–20 verified, fluff-free posts/day to ~3 subscribers.
A single Python 3.11 aiohttp process turns RSS → `NewsItem` → multi-stage
filtering (age, event-first relevance, impact, two-layer dedup) → one AI write
(Groq→Cerebras→OpenRouter, Llama-3.3-70B, JSON contract) → deterministic
anti-hallucination cleaning → Telegram Bot API. **253 tests green.** The active
goal is **post quality**; known rough edges are model-hallucinated years and the
strict `_validate_numbers` behaviour when the source has no digits.

**Role split:** chat-Claude is the strategist (architecture, planning, reviews,
and authoring prompts for Claude Code); **Claude Code is the executor** (clear
prompt in → code, tests, commit, push, report out, minimum questions).

**Security:** chat-Claude may *use* provided keys to act, but must **NEVER output
any secret, ever** — keys are used, never revealed; secrets never enter the repo.
