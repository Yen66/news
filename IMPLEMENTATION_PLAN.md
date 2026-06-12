# IMPLEMENTATION_PLAN.md

Execution plan for @CMW_News (CryptoMacroWorld), authored by chat-Claude (strategist) for Claude Code (executor). Read this together with `PROJECT_UNDERSTANDING.md`. Verified against the live code on branch `main` (`src/pipeline/story.py`, `filters.py`, `dedup.py`, `src/ai/writer.py`, `src/app.py`, `src/models.py`, `src/config.py`).

**Why this plan exists.** A read of ~20 live posts (msgs 301–320) showed the channel's real problem is signal quality and output integrity, not formatting. Concretely observed in production: one story (SpaceX IPO) posted ~8×/day; fabricated quotes/CEO names ("Джейми Роудс", "Джейсон Шен"); broken `[сумма не указана]` / "нет цитаты" artifacts published verbatim; pure geopolitics/war and trivia off-topic; a wrong year ("в 2024 году" in 2026). Phase 1 fixes the feed. Phase 2 adds polish on top of a clean feed.

## EXECUTOR WORKING AGREEMENT (read first — this is the autonomy contract)

Claude Code operates autonomously within the active phase. Rules:

1. **Run the whole phase without pausing between tasks.** Execute tasks in order, top to bottom. Do not ask for confirmation between tasks.
2. **Per-task loop:** implement → run the task's stated tests → if green, `git commit` with a descriptive message and push to `main` → move to the next task. (Deploys are manual on Render, so pushing to `main` does not change the live channel — the human deploys later. This is what makes long autonomous runs safe.)
3. **Report only at the phase boundary.** When every task in the phase is done, append a line to `PROGRESS.md` (date, last commit hash, tasks done, test result) and print a short summary. Then STOP — do not start the next phase. The phase boundary is the human's deploy + review checkpoint.
4. **Stop-and-ask ONLY when:** tests fail in a way the task did not anticipate and you cannot resolve in 2 attempts; the change would be destructive (force-push, history rewrite, deleting files/tables); a task spec is internally contradictory; or the change balloons far beyond the task's stated scope. In those cases, stop and surface the exact problem.
5. **Integrity rules (always):** never claim green when red; never weaken or delete a test to make it pass; keep Russian in bot output, English in logs and docs; respect each task's stated file scope; never revert unrelated commits.
6. **Repo reality checks:** `NewsItem` is a dataclass — use `item.title` / `item.summary` / `item.link` / `item.impact`, never `item.get(...)`. `_render_post`'s local is `body`, parameter is `item`. The feedparser tests fail in the sandbox for environmental reasons (`sgmllib3k`) — exclude them, do not "fix": run `pytest --ignore=tests/test_feeds.py --ignore=tests/test_age_filter.py` (the project's green baseline is 253).

## PHASE 1 — Signal & integrity (do this phase now)

### Task 1.1 — Subject-level burst cap (kills the "same story ×8" feeling)

**Problem.** `StoryDeduplicator` keys on `story_key(title)`, which differs for each article of a multi-article saga (different numbers/words → different keys), so the SpaceX IPO saga was never collapsed. The only cap in `_poll_once` is `max_new_per_cycle` — per poll cycle, not per subject across time.

**Scope (files that may change):** new `src/pipeline/subject.py`; edit `src/app.py` (`_poll_once`), `src/config.py` (new knobs), `src/models.py` (add a coarse `subject_key` helper — reuse `story_tokens` machinery but drop number tokens and keep only the dominant entity/asset/tier token).

**Concrete change.**

* Add `subject_key(title: str) -> str` in `models.py`: like `story_tokens` but number-agnostic — take canonical assets (`_COIN_ALIASES`) plus the single most significant non-stopword proper token; ignore `_NUM_RE` matches entirely. Goal: every "SpaceX IPO …" headline maps to the same subject key.
* New `SubjectCap` in `src/pipeline/subject.py`, modeled on `StoryDeduplicator` but count-based: `Dict[str, list[float]]` (subject_key → timestamps in window). `is_capped(item, now)` → True when count within `SUBJECT_CAP_WINDOW_HOURS` ≥ `MAX_PER_SUBJECT`. `mark(item, now)` appends + prunes. In-memory, same lifecycle as `StoryDeduplicator`.
* Wire in `app.py::_poll_once`: in the queue loop, after the existing `self._story_dedup.is_recent(item)` check and before `queue.put`, add `if self._subject_cap.is_capped(item): subject_capped += 1; continue`. On a successful `put`, also `self._subject_cap.mark(item)`. Construct the cap in `__init__` next to `_story_dedup`. Add `subject_capped` to the poll log line.
* Config: `SUBJECT_CAP_WINDOW_HOURS` (default 12), `MAX_PER_SUBJECT` (default 2).

**Tests.** New `tests/test_subject_cap.py`: same subject 5× in window → exactly 2 pass; distinct subjects unaffected; expiry past the window resets the count. Run `pytest -k "subject or story or dedup"` then the full excluded-suite.

**Ship:** commit and push to `main`. **Guardrails:** do not change `story_key`/`StoryDeduplicator` behavior or the exact-uid `Deduplicator`; this stage is pre-AI (no Russian output touched).

### Task 1.2 — Reject broken integrity artifacts (no more `[сумма не указана]` posts)

**Problem.** `_validate_numbers` replaces an unverifiable number with the literal `'[сумма не указана]'` (writer.py ~line 380) and, when the source has no digits, replaces every body number — producing garbage like "[сумма не указана]триллион … представитель компании нет цитаты" (msg 318) with no spacing. `_validate_body` does not catch this, so it publishes.

**Scope:** `src/ai/writer.py` only.

**Concrete change.**

* In `PostWriter.write`, after `body = _render_post(fields, item)` (~line 746), add a final integrity gate: if the rendered `body` contains any residual artifact marker — `[сумма не указана]`, `нет цитаты`, or a dangling `представитель компании` with no following quote — raise `MalformedPostError` (the processor already drops these quietly: no publish, no mark-seen). Rationale: a post whose core number/claim is unverifiable should not ship.
* In `_validate_numbers`, ensure a replacement never glues to adjacent characters (pad/normalize whitespace around the substitution) — defense in depth for the cases that are not rejected.

**Tests.** Extend the writer tests: a body containing a leaked placeholder → `MalformedPostError`; a msg-318-style input (trillionaire headline, no source digits) → rejected, not published. Run `pytest -k "writer or render or validate"`.

**Ship:** commit and push to `main`. **Guardrails:** do not change the `_validate_numbers` math (thousand/decimal disambiguation fixed in `843b55b`) or the `ТИКЕРЫ:`-line skip.

### Task 1.3 — Kill fabricated quotes & wrong years

**Problem.** Invented quotes ("«Мы рады результатам»") and invented attributions (two different fake SpaceX CEOs in one day) slip past `_filter_quote` / `_clean_made_up_names`. The year ban in the system prompt (writer.py lines ~118, ~165) is ignored (msg 302: "в 2024 году").

**Scope:** `src/ai/writer.py` (strengthen `_filter_quote`; add `_strip_invalid_years`; tighten the system prompt). No other files.

**Concrete change.**

* `_filter_quote`: in addition to the current stop-word rule, drop any quoted segment whose significant words are mostly absent from `item.title + " " + item.summary` (a grounding check, e.g. <40% word overlap). Invented quotes are not in the source, so they get removed.
* Add `_strip_invalid_years(body, item)`: find 4-digit years (`19xx`/`20xx`) in the body that are not present in `item.title + item.summary` and are `< current UTC year`. Drop the sentence containing such a year; if that empties the body, let the integrity gate (Task 1.2) reject the post. Call it inside `_render_post` right after `_validate_numbers`.
* System prompt: state explicitly that the model must never invent a quote — include a quote only if its words appear in the provided title/summary; otherwise omit the quote. Keep the existing "представитель компании" rule and the "no years before 2026" rule.

**Tests.** Invented quote dropped; a quote grounded in the summary kept; "в 2024 году" with a source lacking 2024 → year/sentence removed; a year that IS in the source kept; current year (2026) untouched. Run `pytest -k "quote or year or writer"`.

**Ship:** commit and push to `main`. **Guardrails:** do not drop quotes that ARE grounded in the source; do not strip source-present or current-year dates.

### Task 1.4 — Scope discipline: geopolitics needs a market anchor (highest-risk task)

**Problem.** `filters.py` line ~79 (`TIER1_TERMS |= GEOPOLITICAL_TERMS`) makes pure geopolitics a first-class tier-1 catalyst, so military/diplomatic items ("49 Томагавков по Ирану", troop moves) pass even with no market relevance. The channel is crypto + macro.

**Scope:** `src/pipeline/filters.py` (the geopolitics→tier-1 promotion and `should_publish`), `src/config.py` (reversibility flag).

**Concrete change.**

* Stop auto-promoting `GEOPOLITICAL_TERMS` into `TIER1_TERMS`. Instead, a geopolitical item passes `should_publish` only if it also matches a market anchor (oil/energy/commodity, a major index, a major asset/ticker, or a central-bank term). Pure military/diplomatic items with no market anchor are dropped.
* Gate behind config `GEOPOLITICS_REQUIRES_MARKET_ANCHOR` (default true) so the behavior is instantly reversible if it over-filters.

**Tests.** "49 Tomahawks at Iran" (no market term) → dropped; "Trump threatens Iran oil hub, Brent +2.5%" → kept (oil anchor); ECB/Fed/CPI macro items unaffected. Run `pytest -k "filter or scope or geopol or relevan"`, then the full excluded-suite to confirm the 253 baseline holds.

**Ship:** commit and push to `main`. **Guardrails:** do NOT delete the `GEOPOLITICAL_TERMS` definitions — only remove their automatic tier-1 promotion. Keep the change behind the config flag. If the full suite regresses below baseline, that's a stop-and-ask condition.

### Phase 1 exit

Append to `PROGRESS.md`, print a summary, stop. Human deploys to Render and glances at the live channel before Phase 2.

## PHASE 2 — Polish (only after Phase 1 ships & the feed reads clean)

These are scoped but not yet expanded to task-level detail. chat-Claude will finalize each spec before Phase 2 is executed. Listed here so the plan is complete and the direction is fixed.

* **2.1 Hashtags at the bottom of each post** — deterministic, generated in the `_render_post` footer: ticker (`#BTC`), theme (`#регулирование`, `#макро`, `#отчётность`), geography (`#сша`, `#ес`, `#китай`). No AI, no extra tokens.
* **2.2 Extended emoji type-markers** — beyond ⚡️/⚠️/◉/◎: 💥 large move/deal, 📊 earnings/data, 🏛 regulation/law. Deterministic from tags/keywords.
* **2.3 Inline source short-code in the body** — e.g. "— Reuters", in addition to the existing footer link.
* **2.4 Enable the daily calendar** — `src/events/` exists but is disabled. One 06:00 MSK agenda post (key events, earnings, central-bank decisions, unlocks).
* **2.5 Evening daily digest** — ~22:00 MSK, top 3–5 stories of the day in one summary post (a second AI call; second anchor for non-realtime readers).
* **2.6 Week-ahead pinned events post** — a rolling "events this week" message the bot keeps updated and pinned (mirrors markettwits' pinned-calendar idea).

## APPENDIX — Kickoff prompt (paste once into Claude Code)

```
Read PROJECT_UNDERSTANDING.md and IMPLEMENTATION_PLAN.md in this repo, and
follow the Executor Working Agreement in IMPLEMENTATION_PLAN.md.

Execute PHASE 1 end-to-end now. For each task in order: implement it, run the
task's tests, and after it passes, commit with a clear message and push to main.
Do NOT stop to check in between tasks — only stop on the blockers listed in the
Working Agreement. When all Phase 1 tasks are done, append a line to PROGRESS.md
and give me a short summary, then STOP (do not start Phase 2).
```
