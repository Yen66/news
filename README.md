# News Telegram Bot (Russian-language, $0 hosting)

A self-hosted Telegram bot that watches crypto & financial-markets news
sources, writes a clear Russian-language post for each important item using a
free AI provider, and publishes it to your channel. Built to run on **free
tiers only** (Render free web service + Neon free Postgres + free AI APIs +
UptimeRobot keep-alive).

> Core principle: the AI is called **only** where text or judgement is needed
> (writing a post; optionally proofreading important ones). Everything
> mechanical — fetching feeds, keyword filtering, deduplication, posting,
> error handling, alerts — is plain code.

---

## Architecture

Single process (one Render free **web** service — no Redis, no worker):

- **aiohttp server** with `/` and `/health` for the UptimeRobot keep-alive ping;
- a **background polling task** that checks sources every `POLL_INTERVAL_SECONDS`
  (default 30s);
- a **throttled priority queue** + consumer that processes items; when near the
  daily AI limit it prioritises official / high-impact news.

Layered `src/` (mirrors the `tg-assistant` layout, simplified for free hosting):

```
src/
  config.py            env-driven config (providers, telegram, tunables)
  models.py            NewsItem / Post + uid & fuzzy dedup key
  ai/
    factory.py         AIClient: one AsyncOpenAI client per provider + rotation
    writer.py          writes the post (1 call) + optional editor proofread
  sources/
    catalog.py         the source list (easy to expand) <-- edit me to add feeds
    feeds.py           async RSS / YouTube / Reddit / t.me/s fetchers
  pipeline/
    filters.py         keyword filter, ad/horoscope drop, influential-opinion gate
    dedup.py           exact + cross-source story deduplication
    throttle.py        daily AI-call budget
    processor.py       per-item pipeline + priority queue
  telegram/
    client.py          channel posting + admin error alerts (HTTP Bot API)
  db/
    repository.py      Postgres (Neon) repo + in-memory fallback
  server.py            aiohttp / and /health
  app.py               wiring (poller + consumer + web server)
  main.py              entrypoint:  python -m src.main
```

### Per-item pipeline

1. Code fetches feeds and finds new items.
2. Code filters junk: keyword filter (crypto majors + altcoins; markets:
   S&P 500, Nasdaq, large companies), drops ads & empty "price horoscopes",
   and deduplicates the same story across sources (posted once).
3. **AI writes the post — one call.**
4. Optional: if the post is *Official* **or** high-impact, a second AI
   "editor" call proofreads it (enabled by default for important posts only).
5. Code posts to the Telegram channel.

### AI providers (cross-provider rotation)

All providers are OpenAI-compatible, so one `AsyncOpenAI` client is reused and
only `base_url` / `api_key` / `model` change. On a 429 / quota error the client
automatically rotates to the next provider, in this order:

1. **Groq** — `llama-3.3-70b-versatile` (primary, fast).
2. **Cerebras** — `llama-3.3-70b` (1M tokens/day, very fast; absorbs volume and
   kicks in on Groq limits).
3. **OpenRouter** — a free Llama model (safety net).
4. **Gemini** — present in the code but **disabled by default**
   (`GEMINI_ENABLED=false`); flip the flag to use it later.

Use one legitimate account per provider. Do not create multiple accounts to
dodge limits.

### Post format (Russian, no emoji)

- The substance: what happened, why it matters, the cause, the likely
  consequence/problem — plain language.
- Market-impact assessment (up / down / neutral, and which assets).
- A credibility label: `Официально` or `Слух / не подтверждено`.
- Footer (added by code, deterministic): time in MSK + source link.

Each news item is a separate post, published as fast as possible.

### Opinions rule

Opinions/forecasts are only published when they come from influential people
with a track record (well-known executives, regulators, market-moving
analysts). Random people's predictions are filtered out by `pipeline/filters.py`
(see `INFLUENTIAL_AUTHORS`).

---

## Default choices made for you (ambiguity resolved)

Per the autonomy instruction, sensible defaults were chosen and noted here:

- **Sources**: starts with 4 active English RSS feeds — CoinDesk,
  Cointelegraph, CNBC Finance, and **SEC press releases** (marked *official*).
  Reddit, YouTube and a t.me/s Telegram example are included but **disabled**
  (`enabled=False`) so the minimum runs out of the box. Add more in
  `src/sources/catalog.py`.
- **MSK time** is fixed UTC+3 (Russia has no DST since 2014).
- **Footer is code-generated**, not AI, so the time and link are always exact.
- **Editor proofread** runs only for official/high-impact posts (`impact >= 70`)
  to conserve AI calls.
- **Daily AI budget** defaults to 1000 calls/day (`DAILY_AI_CALL_BUDGET`); when
  under ~20% remains, low-impact items are skipped.
- **No `DATABASE_URL`** => the bot still runs using an in-memory store (dedup
  won't survive a restart). Set Neon for production.
- The Telegram client talks to the **HTTP Bot API directly** (via aiohttp) to
  keep dependencies minimal.

---

## Local development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env        # then fill in values (or use DRY_RUN=true)
python -m pytest            # 44 tests, all mocked (no network, no real keys)
PYTHONPATH=. python -m src.main
```

Tip: set `DRY_RUN=true` in `.env` to log posts instead of sending them.

Run with Docker:

```bash
docker build -t news-bot .
docker run --env-file .env -p 10000:10000 news-bot
# open http://localhost:10000/health
```

---

## Deploy to Render (free)

1. Push this repo to GitHub.
2. In the Render dashboard: **New + → Blueprint**, point it at the repo.
   `render.yaml` provisions a free **web** service running the Dockerfile, with
   the health check at `/health`.
3. Set the secret env vars (listed below) in the Render dashboard.
4. Add an **UptimeRobot** HTTP(s) monitor pointing at
   `https://<your-service>.onrender.com/health` every 5 minutes so the free
   instance doesn't sleep.

---

# WHAT YOU MUST DO

Everything above is built and tested. To go live you only need to create a few
free accounts and paste their secrets into Render (or your local `.env`). Each
secret has a matching, commented entry in `.env.example`.

- [ ] **Create the Telegram channel** you want to publish to.
- [ ] **Create a bot** with [@BotFather](https://t.me/BotFather) → copy the
      token into **`TELEGRAM_BOT_TOKEN`**. Then add the bot to your channel as
      an **administrator** (with "Post messages" permission).
- [ ] **Set the channel** in **`TELEGRAM_CHANNEL_ID`**: `@your_channel` for a
      public channel, or the numeric `-100…` id for a private one.
- [ ] **Get your own Telegram numeric id** from
      [@userinfobot](https://t.me/userinfobot) → paste into
      **`ADMIN_TELEGRAM_ID`** (this is where error alerts go).
- [ ] **Groq key**: sign up at <https://console.groq.com/keys> → create an API
      key → **`GROQ_API_KEY`**. (Primary provider — the bot works with just
      this one.)
- [ ] **Cerebras key** (recommended): <https://cloud.cerebras.ai> → API key →
      **`CEREBRAS_API_KEY`**. Adds volume + automatic fallback.
- [ ] **OpenRouter key** (recommended safety net):
      <https://openrouter.ai/keys> → **`OPENROUTER_API_KEY`**.
- [ ] **Neon Postgres**: create a free project at <https://neon.tech>, copy the
      connection string (Connection Details, `?sslmode=require`) into
      **`DATABASE_URL`**. The bot creates its tables automatically on startup.
- [ ] **Deploy on Render** via the Blueprint (`render.yaml`) and paste all the
      secrets above into the dashboard.
- [ ] **UptimeRobot**: add an HTTP monitor on
      `https://<your-service>.onrender.com/health`, interval 5 min.

Optional / later:
- [ ] Enable **Gemini**: set `GEMINI_ENABLED=true` and add `GEMINI_API_KEY`
      (from <https://aistudio.google.com/app/apikey>).
- [ ] Add more sources in `src/sources/catalog.py` (flip `enabled=True`, or add
      new `Source(...)` rows — RSS, YouTube, Reddit, or `t.me/s` Telegram).

That's the entire checklist. Once those values are set, the bot starts polling,
writing, and publishing on its own.
