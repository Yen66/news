# PROGRESS.md

Phase-boundary log. One line per phase by the executor (Claude Code).
See `IMPLEMENTATION_PLAN.md` for what each phase contains.

- 2026-06-12 — Phase 1 (signal & integrity) complete. Tasks 1.1–1.4 shipped (subject burst cap, integrity gate, quote grounding + invalid-year strip, geopolitics market-anchor gate). Tip commit `6ddbc58`. Tests: **274 passed** (baseline was 253), feedparser tests excluded as documented. Awaiting human deploy + channel review before Phase 2.
- 2026-06-12 — Phase 2 (per-post formatting) complete. Tasks 2.0–2.2 shipped (drop body-echoing quotes, deterministic hashtag line, news-type marker 🏛/📊/💥). Tip commit `ae5b6c8`. Tests: **293 passed** (Phase 1 was 274), feedparser tests excluded as documented. Awaiting human deploy + channel review before Phase 3.
