# CLAUDE.md

Project context for future Claude Code sessions. Read this first.

## PROJECT

- **Name:** news (Telegram channel **@CMW_News**)
- **Purpose:** Autonomous Russian-language Telegram news bot covering crypto,
  macro, forex, commodities, rates, ETF flows, and major US equities.
  Calls an LLM only for writing the post and (optional) editor proofread;
  everything mechanical (fetch / filter / dedup / queue / send) is plain code.
- **Audience:** Russian-speaking crypto + macro traders. Posts are HTML,
  no emoji except `⚡️` prefix and country flags.
- **Hosting:** Render free web service + Neon Postgres free tier +
  UptimeRobot keep-alive ping.
- **Budget:** $0. Only free tiers and free LLM endpoints (Groq / Cerebras /
  OpenRouter free models).
- **Branch policy:** push directly to `main` (solo project). The current
  feature branch is `claude/gifted-babbage-s6Rm2` — work happens there only
  if explicitly requested; otherwise commit straight to `main`.

## ARCHITECTURE

Single Python 3.11 process, one container:

- **`aiohttp` web server** (`src/server.py`) — keeps Render's free web
  service alive. Endpoints:
  - `GET /` — status JSON (uptime, last poll, queue size, provider in use).
  - `GET /health` — `200 ok` for UptimeRobot.
  - `GET /test-post` — pull one fresh item, bypass dedup/seen, run the full
    pipeline once. Used for prod smoke tests.
- **Background tasks** (started in `NewsBotApp` at `src/app.py`):
  - **Poller** — every `POLL_INTERVAL_SECONDS` (default 30) fetches all
    enabled RSS feeds in parallel, runs the filter pipeline, pushes
    survivors onto the priority queue. Cap per cycle = `MAX_NEW_PER_CYCLE`.
  - **Consumer** — drains the queue. Enforces a minimum
    `AI_CALL_MIN_INTERVAL_SECONDS` (default 15s) gap between AI calls so we
    don't burst-trip provider rate limits.
- **Supervisor** — both tasks have done-callbacks that log + alert admin on
  crash and restart them.

## KEY FILES

### `src/`

- `main.py` — entrypoint; loads config, builds `NewsBotApp`, runs forever.
- `app.py` — `NewsBotApp`. Polling loop (`_poll_once`), age filter
  (`_filter_by_age`), historical filter, dedup, story dedup, cap, queue
  push. Owns the consumer task and `/test-post` handler.
- `config.py` — env-driven `Config` dataclass + `_load_providers` +
  `normalize_channel_id` (`@name` / `t.me/x` / `-100…` all accepted).
  `_DEFAULT_MODELS` lives here (Groq `llama-3.3-70b-versatile`,
  Cerebras `llama3.3-70b`, etc.).
- `models.py` — `NewsItem`, `Post`, `story_key()` (cross-source dedup key:
  normalised numbers + tickers, falls back to significant words).
- `server.py` — aiohttp routes (`/`, `/health`, `/test-post`).

### `src/ai/`

- `factory.py` — `AIClient`. Builds one `AsyncOpenAI` per provider, ordered
  by `priority`. `complete()` rotates on quota errors, honours `Retry-After`
  (header / body / regex from message) once per provider before rotating.
  Raises `AllProvidersExhausted` when nothing's left.
- `writer.py` — `PostWriter`. Builds system+user prompts, calls
  `AIClient.complete`, then post-processes: `sanitize_text` (Cyrillic /
  Latin / digits / punctuation / `↑↓→·` only — strips CJK), strip URLs,
  drop forbidden phrases (`Суть:`, `Оценка:`, `не указана`, etc.),
  `_keep_concrete_sentences` (drops filler), `_clean_prefix` (`⚡️` +
  country-flag whitelist), `credibility_label()` per-article
  (`◎ Слух` if rumor language, else `◉ Официально`). `⚡️` only allowed
  for items published within `BREAKING_WINDOW = 2h`.

### `src/pipeline/`

- `filters.py` — **tiered relevance + impact scoring.**
  `TIER1_TERMS` (HIGH: BTC/ETH, central banks, CPI/PPI/NFP, ETF flows,
  SEC, DXY, S&P/Nasdaq, Mag 7, BlackRock/Coinbase/MicroStrategy/Binance)
  and `TIER2_TERMS` (MEDIUM: large-cap equities, commodities, earnings/
  M&A, alt-coins, FX). `matches_keywords` requires a tier term (official
  sources always relevant). `score_impact` is a 0-100 model: base +
  official +25 + tier-1 (×18, cap 2) + tier-2 (×8, cap 2) + catalyst
  (×10, cap 2), minus penalties for `REGIONAL_NOISE_TERMS`, commentary,
  and catalyst-free move recaps (`is_routine_move`) — penalties only bite
  with no tier-1 anchor. `should_publish` is the categorical gate (ad /
  horoscope / opinion-without-influential-author / historical).
  `filter_items` rescores and **rejects anything below
  `MIN_IMPACT_TO_PUBLISH`** (official bypasses). Boundary-based — `ban`
  does not match `bank`.
- `dedup.py` — `Deduplicator`: permanent uid-based seen-set (backed by
  the repository on startup).
- `story.py` — `StoryDeduplicator`: time-windowed (`STORY_DEDUP_WINDOW_HOURS`,
  default 6h) cross-source dedup by `story_key`.
- `processor.py` — `Processor.process_one` (dedup → budget → AI spacing →
  writer → publish → mark seen + archive **only on success**) and
  `ProcessingQueue` (asyncio priority queue by impact).
- `throttle.py` — `DailyBudget` (resets at UTC midnight).

### `src/sources/`

- `catalog.py` — list of `Source` dataclasses (name, url, type, official).
  16 enabled feeds; 4 Reddit feeds disabled.
- `feeds.py` — `FeedFetcher`. Cache-busting headers + `_cb=<ts>` query
  param, browser User-Agent. `_parse_rss` (feedparser) and
  `_parse_telegram` (BS4 over `t.me/s/<channel>`).

### `src/db/`

- `repository.py` — `PostgresRepository` (asyncpg, two tables:
  `sent_news`, `archive`) and `InMemoryRepository` fallback when
  `DATABASE_URL` is empty.

### `src/telegram/`

- `client.py` — direct HTTP `sendMessage` via `aiohttp`.
  `publish(text)` → channel, `alert_admin(text)` → admin. HTML parse mode,
  link previews disabled. 400/403/404 each get a specific log hint.

### Top-level

- `render.yaml` — Render Blueprint (free web service, Docker, env var
  declarations).
- `Dockerfile` — slim Python 3.11.
- `requirements.txt` / `requirements-dev.txt`.
- `pytest.ini` — `asyncio_mode = auto`.
- `.env.example` — every env var the app reads.
- `tests/` — 105 tests; conftest exposes `make_item`, `FakeAIClient`,
  `FakeTelegram`.

## CONFIGURATION (env vars)

All read in `src/config.py`. **Note: config lives at `src/config.py`, not
`src/core/config.py`.**

### Telegram

| Var | Default | Purpose |
|---|---|---|
| `BOT_TOKEN` *(or `TELEGRAM_BOT_TOKEN`)* | — | Bot API token. |
| `CHANNEL_ID` *(or `TELEGRAM_CHANNEL_ID`)* | — | `@CMW_News` or `-100…`. |
| `ADMIN_ID` *(or `ADMIN_TELEGRAM_ID`)* | — | Numeric user id for alerts. Admin must `/start` the bot once or 403s. |

### Database

| Var | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `""` | Neon Postgres URL. Empty → in-memory repository (resets each restart). |

### AI providers (any subset enabled; auto-disabled if key missing)

| Var | Default | Purpose |
|---|---|---|
| `GROQ_API_KEY` | — | Groq priority 1. Model: `llama-3.3-70b-versatile`. |
| `CEREBRAS_API_KEY` | — | Cerebras priority 2. Model: `llama3.3-70b` (no hyphen). |
| `OPENROUTER_API_KEY` | — | OpenRouter priority 3 (free tier). |
| `GEMINI_API_KEY` | — | Disabled by default (non-OpenAI-compatible). |
| `<PROVIDER>_MODEL` | per `_DEFAULT_MODELS` | Per-provider override. |

### Pipeline tuning

| Var | Default | Purpose |
|---|---|---|
| `POLL_INTERVAL_SECONDS` | `30` | Fetch cadence. |
| `QUEUE_MAX_SIZE` | `100` | Hard ceiling on the priority queue. |
| `MAX_NEW_PER_CYCLE` | `3` | Anti-flood — max items queued per poll. |
| `MAX_ARTICLE_AGE_HOURS` | `24` | Drop anything older than this or with no pubDate. |
| `STORY_DEDUP_WINDOW_HOURS` | `6.0` | Window for cross-source story dedup. |
| `MIN_IMPACT_TO_PUBLISH` | `45` | Min 0-100 impact score to publish; drops regional/commentary/recap noise. Official sources bypass. |
| `ENABLE_EDITOR` | `true` | Run a second AI pass to proofread. |
| `AI_CALL_MIN_INTERVAL_SECONDS` | `15.0` | Min gap between consecutive AI calls. |
| `DAILY_AI_CALL_BUDGET` | `100` | Soft cap; low-impact items skip once exhausted, official/high-impact still go through. |
| `REQUEST_TIMEOUT_SECONDS` | `10` | HTTP timeout for fetch + Telegram. |
| `HTTP_PORT` | `10000` | aiohttp listen port (Render sets `$PORT`). |
| `LOG_LEVEL` | `INFO` | Standard logging level. |
| `DRY_RUN` | `false` | True → don't actually call Telegram. |

## FILTER PIPELINE (order matters)

In `app.py::_poll_once`:

1. **Age filter** — drop / mark-seen anything older than
   `MAX_ARTICLE_AGE_HOURS` (or missing `published`).
2. **Historical filter** — `filters.is_historical`. Title containing only
   years ≤ last year, or body with retrospective phrases (`в 2022 году`,
   `back in 2023`, `year-in-review`, `ретроспектив*`, `годовщин*`) AND no
   current/last-year date anywhere. Mark seen so we don't re-evaluate.
3. **Relevance + impact filter** — `filters.filter_items` runs
   `should_publish` (`matches_keywords` over the tiered vocab AND not
   `is_ad` / `is_price_horoscope` / `is_opinion`-without-influential-
   author / historical), then rescores `impact` via `score_impact` and
   **drops anything below `MIN_IMPACT_TO_PUBLISH`** (regional indexes,
   generic commentary, catalyst-free move recaps). Official bypasses the
   bar. Logged as `low_impact=N` in the poll line.
4. **Exact dedup** — `Deduplicator.filter_new` by `uid` (sha256 of
   guid/link). DB-backed, permanent.
5. **Story dedup** — `StoryDeduplicator.is_recent(story_key)` against a 6h
   window. Drops the same story arriving from a second source.
6. **Cap** — keep at most `MAX_NEW_PER_CYCLE` items, sorted by impact desc.

Queued items are then consumed at the AI-spacing rate.

## AI PROVIDER ROTATION

`src/ai/factory.py::AIClient.complete`:

1. Providers sorted by `priority` (Groq 1 → Cerebras 2 → OpenRouter 3).
2. For each provider, up to **2 attempts**:
   - On success → return `(text, provider_name)`.
   - On a 429 / quota error:
     - Parse `Retry-After` from header → body `retry_after_seconds` →
       message regex (`try again in 3s`, `500ms`).
     - If hint exists and ≤ `MAX_RETRY_AFTER_SECONDS` (30s):
       `await asyncio.sleep(hint)` and **retry the same provider once**.
     - Otherwise rotate to next provider.
   - On any other exception: log + rotate.
3. If all providers exhausted → raise `AllProvidersExhausted` (caller
   logs + alerts admin, item stays unposted but is NOT marked seen).

Consumer-side, `Processor._space_ai_calls()` enforces a minimum gap of
`AI_CALL_MIN_INTERVAL_SECONDS` between calls using `time.monotonic` —
applied after dedup/budget gates so we never sleep for items we'd skip.

## POST FORMAT SPEC

HTML, no Markdown, link previews off. Russian only.

Structure (`PostWriter._render_post`):

```
[ПРЕФИКС] [ТЕКСТ ≤3 предложений]

<code>[ТИКЕРЫ]</code>     ← optional, only if AI extracted prices

[МЕТКА] · <a href="URL">Source</a>
```

Rules:

- **Prefix:** `⚡️` only when the article was published within the last
  **2 hours** (`BREAKING_WINDOW`). Country flag (🇺🇸 🇪🇺 🇨🇳 🇯🇵 🇬🇧 etc.)
  allowed any time. Whitelist enforced in `_clean_prefix`.
- **Body:** ≤3 sentences. Every sentence must contain a concrete fact —
  number, name, date, quote. `_keep_concrete_sentences` drops filler. Lead
  with the number / quote, not a setup clause.
- **Ticker line** (optional): monospace `<code>`. AI is instructed to
  extract `BTC $103,500 (+2.1%)`-style fragments.
- **Last line:** credibility label + ` · ` + clickable source.
  - `◉ Официально` — official source (SEC / Fed / ECB) OR body has
    official language (`announced`, `confirmed`, `подтвердил`).
  - `◎ Слух` — body has rumor language (`reportedly`, `sources say`,
    `could`, `may`, `по слухам`). **Rumor beats official** — established
    outlets reporting unconfirmed claims still get `◎ Слух`.
- **Sanitisation:** `sanitize_text` keeps Cyrillic + Latin + digits +
  punctuation + currency + `↑↓→·`; strips CJK and other scripts.
- **Strip:** URLs from body, plus literal `Суть:` / `Оценка:` / `Метка:` /
  `Время:` / `не указана`.

## RSS SOURCES

In `src/sources/catalog.py`. 16 enabled, 4 Reddit feeds disabled. Watch
`per_source={…}` in the `Poll #N` log line — if a source shows `0` cycle
after cycle, mark it disabled.

### Crypto

| Source | Status |
|---|---|
| CoinDesk | working |
| Cointelegraph | working |
| Decrypt | working |
| The Block | working |
| CryptoSlate | working |
| Blockworks | working |
| BeInCrypto | working |
| Bitcoin Magazine | working |
| Forkast | working |

### Macro / equities

| Source | Status |
|---|---|
| CNBC | working |
| MarketWatch | working |
| Investing.com | working |
| ZeroHedge | working |

### Official (regulators)

| Source | Status |
|---|---|
| SEC press releases | working |
| Federal Reserve press releases | **404** — needs new URL |
| ECB news | **404** (the `.html` endpoint flagged previously) |

### Disabled

- Reuters (RSS dead — DNS).
- Reddit `r/CryptoCurrency`, `r/Bitcoin`, `r/ethfinance`, `r/stocks`
  (noise too high).

## KNOWN ISSUES

- **Cerebras model name** — currently `llama3.3-70b` (no hyphen after
  `llama`). If Cerebras renames again, expect quota-shaped 400s; check
  their docs and update `_DEFAULT_MODELS`.
- **Groq daily token cap** — ~100K TPD on free tier. Bursty hours
  exhaust it; rotation kicks in but expect Cerebras-as-primary stretches.
- **OpenRouter free tier** — 8 RPM cap on most free models. The 15s
  spacing keeps us under it, but parallel `/test-post` calls can trip it.
- **Fed / ECB feeds returning 404** — URLs need updating in
  `src/sources/catalog.py`.
- **Sandbox can't verify feeds** — outbound HTTP is blocked in the
  build/preview env; feed reachability has to be confirmed from Render
  logs after deploy.
- **Stop-hook "Unverified" flag** — commits aren't GPG-signed because no
  signing key is available in the remote-exec env. Cosmetic; ignore.

## RECENT DECISIONS

- **Post format redesign** — dropped ALL-CAPS headlines and the
  `Суть:/Оценка:/Метка:/Время:` template; now lead with the concrete
  number/quote, ≤3 sentences, optional monospace ticker line, single
  credibility-label + source footer.
- **Per-article credibility** — outlet reputation alone is no longer
  enough; rumor language (`reportedly`, `sources say`, `по слухам`)
  forces `◎ Слух` even on established outlets.
- **"Concrete fact required" sentence filter** — `_keep_concrete_sentences`
  drops sentences with no number / name / date.
- **Breaking-prefix time gate** — `⚡️` only for items <2h old; country
  flags are not time-gated.
- **CJK sanitisation** — `sanitize_text` whitelist after we saw stray
  Chinese characters from one provider's output.
- **Cross-source story dedup** — 6h windowed `story_key` so the same
  story doesn't post 4 times when CoinDesk + Cointelegraph + Decrypt +
  Blockworks all carry it.
- **24h age filter + historical filter** — RSS replays + retrospective
  pieces (`в 2022 году…`, year-in-review) are dropped before AI.
- **AI-call spacing** — 15s minimum between consumer AI calls; eliminated
  burst-induced 429s.
- **Mark-seen only on success** — `Processor.process_one` only marks the
  uid seen / archives when `publish()` returns `True`. Earlier bug
  poisoned `sent_news` with 82 phantom items during a token misconfig.
- **`BOT_TOKEN` / `CHANNEL_ID` env names accepted** alongside the longer
  `TELEGRAM_*` variants.

## DEVELOPMENT WORKFLOW

- **Branch:** push directly to `main` unless instructed otherwise. The
  remote-exec branch (`claude/gifted-babbage-s6Rm2`) is for in-session
  work that hasn't been authorised for `main` yet.
- **Tests:** `pytest` — must stay green. Current count: **105**. Add a
  test for every behavior change; conftest provides `make_item`,
  `FakeAIClient`, `FakeTelegram`.
- **Commits:** authored as `Claude <noreply@anthropic.com>`. End every
  commit message with the session URL footer.
- **Never include** the model identifier (`claude-opus-4-*`, etc.) in
  any artifact pushed to the repo (commits, PR bodies, code comments).
- **Push flow** (PAT lives only in chat — scrub after each push):
  ```
  git remote set-url origin https://<TOKEN>@github.com/Yen66/news.git
  git push origin HEAD:main
  git remote set-url origin https://github.com/Yen66/news.git
  ```
  Then remind the user to rotate the PAT.
- **Diagnostics on Render:**
  - `Poll #N: fetched=X old=X historical=X kept=X new=X story_dup=X queued=X (cap=X) per_source={…}`
  - Empty `new=` after fresh deploy → check `DATABASE_URL` for phantom
    seen-set; `TRUNCATE sent_news;` if needed.
  - 403 from Telegram on startup → admin must `/start` the bot once.
  - 404 from Telegram → token / channel id mismatch (check the
    startup log line that prints the resolved channel id).
