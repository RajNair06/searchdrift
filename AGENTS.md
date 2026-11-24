# SearchDrift — Agent Context

Shared context for any coding agent working in this repo (Claude Code, OpenCode, …).
`CLAUDE.md` imports this file.

## Who this is for

The user is a **beginner learning backend, applied AI and infra engineering by
building this one project**. The goal: be ready to interview for applied-AI /
backend / AI-infra internships or junior roles at startups by mid-January 2027.

So the job is **teaching while building**, not just shipping code:

- Explain from first principles: the *why* (what problem this solves, what breaks
  without it), then the *what*, then the technical details.
- Go **one entity / one topic at a time**. Don't dump multi-entity designs.
- Start with the simplest version that works. Add a concept only when its
  problem is felt. Don't pull later weeks' features forward.
- Ask when a design decision is ambiguous, instead of guessing.

## How we work: learn + build, one chunk at a time

Every work session takes **one small chunk** of the current week's build
checklist (in `PROGRESS.md`): small enough to build, explain and test in one
sitting, e.g. "FastAPI app + `/health`", not "the whole API". Never build the
whole week in one go. Each chunk follows the same loop:

1. **Name the chunk** and which week's goal it serves.
2. **Teach the fundamentals it touches.** Map the chunk to that week's
   *Fundamentals to master* in `docs/plan.md` and teach those topics from first
   principles, using the chunk as the concrete example. (A connection pool →
   TCP/TLS handshake cost and pooling; a vendor adapter → HTTP, timeouts,
   connect vs read; the ledger → transactions and `SELECT … FOR UPDATE`.)
   Fundamentals that no chunk naturally reaches get taught on their own, with a
   small example in this codebase where possible.
3. **Build it**: the simplest code that works, following the locked entity docs
   in `docs/entities/`.
4. **Explain the code, two ways:**
   - **Why it's done this way:** the decision, the alternative we rejected, and
     what would break without it.
   - **How it works:** walk the code path in order (what runs at startup, what
     runs per request, where data flows), down to individual lines for anything
     non-obvious. Code comments carry the short *why* for non-obvious lines;
     the longer teaching goes in the chat, not in essays inside the code.
5. **Prove it:** tests for the happy path **and** the failure path, plus
   running it for real (curl the endpoint, query the table).
6. **Break it** (when useful): show the failure the design prevents, e.g. stop
   Postgres and watch `/health` return 503.
7. **Self-test:** end with 2–3 questions the user should be able to answer
   without notes. They feed the Sunday self-test; tick a fundamental in
   `PROGRESS.md` only once the user can explain it.
8. **Checkpoint:** update progress (next section), then stop and let the user
   absorb before starting the next chunk.

## Keeping progress up to date (required, not optional)

`PROGRESS.md` is the memory between sessions: a new agent chat knows only what
it says. If it's stale, the next session starts from the wrong place.

**When to update:** at every checkpoint, i.e. after every finished chunk,
after every design decision the user confirms, and before ending a session.
Don't wait until "the end"; a session can stop at any time.

**What to update in `PROGRESS.md`:**

| Section | What to change |
|---|---|
| **Current position** | One line: where we are now (week + chunk). Move the ⬅️ marker. |
| **Next actions** | Mark finished items ✅, the current one 🔨, and name the next chunk. |
| **Week N build checklist** | Tick `[x]` items that are built **and** tested; add a short note of anything surprising (e.g. "host port 15432, not 5432"). |
| **Week N fundamentals** | Tick `[x]` only when the user has explained the topic back without notes, never just because it was taught. |
| **Session log** | One row per session: date, what was built, decisions made and *why*, problems hit. |

The user keeps their daily learning log outside this repo; don't add one here.

**Also keep in sync:**

- **`AGENTS.md` → "Current status"**: a short summary for any agent (what's
  done, what's next). Update it when a chunk finishes.
- **Entity docs' status line** (`docs/entities/*.md`): `draft — under review`
  → `locked (date)` when the user approves; record any later change to a locked
  doc as a dated note in that doc.
- **`docs/plan.md`**: never rewrite the user's plan; add a dated note where
  scope changed (as done for fresh questions).

Finish each checkpoint by telling the user, in one line, what was updated.

## What SearchDrift is

AI agents and RAG apps depend on search APIs (Tavily, Exa, Serper). When a
vendor quietly gets worse, every app on top of it gets worse too. **SearchDrift
measures search vendors over time against a frozen, hand-written gold set and
tells you when one of them really changed — beyond its normal noise.**

The one sentence the system must be able to say:

> "On this frozen question set, measured this way, vendor X scored 0.71 ± 0.03.
> Compared to its baseline it dropped by 0.06, and that drop is bigger than its
> normal noise (significant after correction)."

Full explanation and the entity map: **`docs/project.md`**.
Schedule (8 weeks, Nov 23 2026 – Jan 17 2027): **`docs/plan.md`**.

## Core loop

1. **Gold set** — hand-written questions + correct answers, versioned, then frozen.
2. **Run** — ask every question to every vendor, N repeats. Each
   (question × vendor × repeat) is a **trial**.
3. **Score** — deterministic precision / recall / F1 against the gold answers.
4. **Drift** — compare to a frozen **baseline** with paired bootstrap CIs and
   Holm/BH correction.

Two measurement tiers:
- **Tier 1, direct vendor (primary drift signal):** fixed query → raw results → scored. No LLM noise.
- **Tier 2, agent in the loop (secondary):** an LLM agent chooses queries/tools.

## Entities (overview — deep dives in `docs/entities/`, one at a time)

| Group | Entities |
|---|---|
| Truth | GoldSet, Question (gold answer stored inside Question for now) |
| Instruments | Vendor |
| Execution | Run, Trial (becomes the job queue in week 3), Score |
| Cost & reproducibility | Cassette, LedgerEntry, LLMCall |
| Drift | Baseline, DriftReport |
| Later / stretch | JudgeVerdict, HumanLabel |

Rule: **fewest tables that work**; split an entity out only when a real need shows up.

## Decisions already made (by the plan)

- **One codebase, two process types:** a control-plane API (FastAPI) and N
  data-plane workers, plus Postgres and Redis, all in Docker Compose.
  The API never calls vendors or LLMs; only workers spend credits.
- **Postgres is the job queue** (week 3): workers claim trials with
  `FOR UPDATE SKIP LOCKED`, hold leases with heartbeats; expired leases are
  reclaimed. Re-execution is idempotent via unique constraints + cassettes.
- **Asyncio throughout:** FastAPI, SQLAlchemy 2.0 async + asyncpg, httpx.
- **Cassettes:** every external call is recorded, keyed by a request hash.
  Replay is the default in dev, tests and CI (zero network in CI).
- **Credit ledger:** budget check + reservation in the same DB transaction,
  before any live call. Unknown-outcome calls are `uncertain`, never charged twice.
- **Redis distributed rate limiter** per vendor / per LLM provider, shared across workers.
- **Deterministic scoring is primary.** An LLM judge is a stretch goal and only secondary.
- **LLM router** (week 4): one internal gateway for every LLM call. Fallback
  chain Gemini → Groq → Ollama, retries with backoff, circuit breaker per
  provider, token/cost accounting, model version requested vs. observed.
- **Provenance on every run:** gold-set version, prompt version, model version
  requested vs. observed, full config, code version (git SHA).
- **Real vendors from week 1.** A mock vendor is fine for automated tests and
  chaos/load tests, but the user wants to hit real APIs early.

## Stack

Python 3.12 · uv · FastAPI · SQLAlchemy 2.0 (async) · asyncpg · Alembic ·
PostgreSQL · Redis · httpx · pytest + pytest-asyncio · ruff · Docker Compose ·
OpenTelemetry + Prometheus/Grafana (week 6)

## Credits and keys

- Search vendors in `.env`: Tavily (1,000/month), Exa (2,500 one-time),
  Serper (2,500 one-time), Firecrawl and SerpApi (not in the MVP's 3 vendors).
- LLMs: Gemini free tier, Groq free tier, local Ollama.
- Free credits are scarce: never make a live call that a cassette could serve.
  Live calls should be deliberate and budget-checked.

## Current status

See `PROGRESS.md` (local, gitignored) for the current position and session log.

- **Week 1 starts Mon 2026-11-23.**
- Done: `docs/project.md`, `docs/plan.md`, and locked deep dives for all week 1
  entities in `docs/entities/`: Question, GoldSet, Vendor, Run, Trial, Cassette,
  LedgerEntry.
- Week 1 build in progress: project skeleton done (uv, Compose with Postgres
  on host port 15432 and Redis on 16379, FastAPI `/health`). Next chunk:
  Alembic schema v1. Details in the week 1 checklist in `PROGRESS.md`.

## Docs layout

```
docs/
├── plan.md          # 8-week plan (schedule, fundamentals, deliverables)
├── project.md       # what SearchDrift is + entity map + open questions
└── entities/        # one deep-dive doc per entity, written when we build it
```

Entity deep-dive format (`docs/entities/{Name}.md`): what it is · why it exists ·
how it fits the core loop · every field with type and justification · state
machine (if any) · API endpoints (if any) · subtleties and edge cases. Only the
fields needed now; mark which week later fields arrive in.

## Rules

- **Derived data rule:** store a computed value only if its source is immutable
  *and* the stored copy enables something the source can't (usually an index).
  Example kept: `Cassette.request_hash`. Examples rejected: credits spent
  (source changes), parsed trial results, `Run.config_hash` (no job of its own).

- **Commit only when the user says so.** Docs are currently uncommitted.
- Never commit `.env` (API keys). Gitignored: `.env`, `PROGRESS.md`, `opencode.json`.
- Done means explainable: the user can explain it without notes (Sunday self-test).
- Weeks are targets, not deadlines: don't skip understanding to stay on schedule.
- Project name is **SearchDrift**.
