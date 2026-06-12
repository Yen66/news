# IMPLEMENTATION_PLAN_PHASE2.md

Detailed task specs for Phase 2 of @CMW_News. Supersedes the brief "PHASE 2 — Polish" outline in `IMPLEMENTATION_PLAN.md`. Follow the Executor Working Agreement in `IMPLEMENTATION_PLAN.md` (run the phase without pausing between tasks; per task implement → test → commit → push; report only at the phase boundary; stop only on the listed blockers; Russian in bot output, English in logs/docs; `NewsItem` is a dataclass; exclude the feedparser tests; green baseline is 274).

Verified against `src/ai/writer.py` on `main`: posts are assembled by `_render_post(fields, item)`. Prefix is `_clean_prefix` (allows only the ⚡️ bolt, ⚠️ warning, or one country flag). Footer is `{credibility_label} · <a href=link>source_name</a>`. A monospace `<code>` ticker line is added only when prices are present.

**Regrouping decisions (by chat-Claude):**

* The original "2.3 inline source short-code" is dropped — redundant with the existing footer that already names the source on every post.
* The scheduled-content features (daily calendar, evening digest, week-ahead pinned) are moved to a future Phase 3 — they are new content types (scheduler, extra AI call, Telegram pin/edit, rolling state), each needing its own spec and deploy checkpoint. They are NOT in this phase.

## PHASE 2 — Per-post formatting (deterministic render-layer only)

All three tasks are deterministic, add no AI calls and no tokens, and live in `src/ai/writer.py` (plus small new helper modules + tests). They change the appearance of every new post, so they become visible immediately on the human's next manual Render deploy.

### Task 2.0 — Drop body-echoing quotes (quick quality fix)

**Problem.** Observed in production (msg, Adam Back item): a quote that merely restates the sentence it follows ("…назвав план … отдельной альткойном. Adam Back: «план … — это отдельная альткоин».") — grammatically rough and adds no information. This is the mild residue of the old filler-quote pattern.

**Scope:** `src/ai/writer.py` (`_filter_quote`).

**Concrete change.** Extend `_filter_quote`: in addition to the current rules, also remove a quote whose content closely duplicates a sentence already in the body (high word-overlap, e.g. ≥70% of the quote's significant words appear in the surrounding non-quote text). A quote should add a voice/claim, not echo the narration. Keep quotes that introduce new information.

**Tests.** Echo-of-body quote → removed; a quote that adds a distinct claim → kept; the existing grounding/stop-word rules still pass. `pytest -k "quote"`. **Ship:** commit + push. **Guardrails:** do not drop grounded, information-adding quotes; do not touch `_clean_made_up_names` / `_validate_numbers`.

### Task 2.1 — Hashtags at the bottom of every post

**Goal.** Append a deterministic hashtag line as the last line of the post (below the source footer): ticker + theme + geography. Turns the channel into a searchable archive (the markettwits mechanic), at zero token cost.

**Scope:** new `src/ai/hashtags.py`; edit `src/ai/writer.py` (`_render_post`); new `tests/test_hashtags.py`. May import `_COIN_ALIASES` from `src/models.py`.

**Concrete change.**

* `build_hashtags(item, body, tickers) -> list[str]` in `hashtags.py`, returning an ordered, de-duplicated, capped (max 4) list:
   1. **Ticker tags** — from the `ТИКЕРЫ` field and asset names in title/body, normalised via `_COIN_ALIASES` (e.g. `bitcoin`/`btc` → `#BTC`, `avalanche`/`avax` → `#AVAX`). Upper-cased ticker.
   2. **Theme tags** — from a small curated `THEME_MAP` keyword→tag in this file: e.g. regulation/SEC/закон → `#регулирование`; ETF → `#ETF`; earnings/выручка/results → `#отчётность`; rate/CPI/inflation/Fed/ECB → `#макро`; IPO/листинг → `#IPO`; hack/exploit → `#безопасность`. Match case-insensitively against `title + summary + body`.
   3. **Geo tags** — from a small `GEO_MAP` (country term / flag emoji → tag): US/США/Fed → `#сша`; ЕС/ECB/Europe → `#ес`; China/Китай → `#китай`; Russia/Россия → `#россия`. Reuse the flag already chosen by the prefix when present. Order: tickers, then themes, then geo. Cap the total at 4 to avoid clutter.
* In `_render_post`, after building `source_part`, compute `tags = build_hashtags(...)` and, if non-empty, append `"", " ".join(tags)` as the final lines (hashtags are plain text, space-joined, no HTML).

**Tests.** `tests/test_hashtags.py`: a BTC item → contains `#BTC`; an ECB rate item → `#макро` and `#ес`; an item with no matchable signal → empty list (no trailing blank line); cap of 4 respected; output deterministic for the same input. Then run the full excluded-suite — update any `_render_post` golden tests to include the new final line (realign expected output; do not weaken assertions).

**Ship:** commit + push. **Guardrails:** deterministic only — no AI, no network. Never emit more than 4 tags. Do not alter the body, ticker line, or source footer themselves.

### Task 2.2 — Extended emoji type-markers

**Goal.** Beyond the existing ⚡️ (breaking) / ⚠️ (upcoming) / 🏳 (country flag), add a deterministic news-type marker: 💥 large move/deal, 📊 earnings/data, 🏛 regulation/policy. Lets the reader scan the feed by symbol.

**Scope:** `src/ai/writer.py` (`_clean_prefix` and/or a new `type_marker` helper, and the prefix assembly in `_render_post`); tests.

**Concrete change.**

* Add `type_marker(item, body, tickers) -> str` (deterministic, computed in code — do not trust the model to pick it):
   * `🏛` if regulation/policy signal (SEC, регулятор, закон, ruling, sanction, Clarity Act, etc.);
   * `📊` if earnings/data signal (earnings, выручка, results, CPI, jobs, GDP, quarterly);
   * `💥` if a large move/deal (a ≥10% change in the ticker line, or surge/plunge/record/обвал/взлёт, or a multi-$bn M&A);
   * else `""`. Pick one (first match in the order above).
* In `_render_post`, compose the prefix as `f"{type_marker}{flag_or_bolt}"` (type marker first, then the existing flag/⚡️/⚠️), trimming spaces. Keep it to at most one type marker + one flag/bolt — never a pile of emoji.
* Preserve existing rules: `is_upcoming_speech` still forces ⚠️; the ⚡️ bolt is still gated to items newer than 2h.

**Tests.** A regulation item → prefix contains 🏛; an earnings item → 📊; a ≥10% move → 💥; a plain item → no type marker; ⚠️ upcoming-speech path and the ⚡️ recency gate still behave. `pytest -k "prefix or marker or render"`.

**Ship:** commit + push. **Guardrails:** additive only — do not remove or weaken the ⚡️/⚠️/flag logic; markers are computed deterministically, never read from model output. If combining markers ever produces >2 leading emoji, that's a bug — keep it to one type marker plus one flag/bolt.

### Phase 2 exit

Append to `PROGRESS.md`, print a summary, stop (do not start Phase 3). Human deploys to Render and eyeballs the new post formatting (hashtags present, markers sensible, no clutter, footer intact).

## PHASE 3 — Scheduled content (specs to be written later, NOT now)

Outline only — chat-Claude will expand each into task-level detail (and read `src/events/`) before Phase 3 runs:

* **3.1 Daily calendar** — enable the existing `src/events/` path; one 06:00 MSK agenda post (key events, earnings, central-bank decisions, token unlocks).
* **3.2 Evening digest** — ~22:00 MSK summary of the day's top 3–5 stories (a dedicated AI call; second anchor for non-realtime readers).
* **3.3 Week-ahead pinned post** — a rolling "events this week" message the bot keeps updated and pinned.

## APPENDIX — Kickoff prompt (paste once into Claude Code)

```
Read IMPLEMENTATION_PLAN.md and IMPLEMENTATION_PLAN_PHASE2.md in this repo, and
follow the Executor Working Agreement in IMPLEMENTATION_PLAN.md.

Execute PHASE 2 from IMPLEMENTATION_PLAN_PHASE2.md end-to-end now (tasks 2.0,
2.1, 2.2 in order). For each task: implement it, run the task's tests, and after
it passes, commit with a clear message and push to main. Do NOT stop to check in
between tasks — only stop on the blockers listed in the Working Agreement. When
all Phase 2 tasks are done, append a line to PROGRESS.md and give me a short
summary, then STOP (do not start Phase 3).
```
