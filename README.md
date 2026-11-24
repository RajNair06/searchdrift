# SearchDrift

**Is your search API getting worse?** SearchDrift measures search vendors
(Tavily, Exa, Serper) over time against a frozen, hand-written question set and
tells you when one of them *really* changed — not just noise.

AI agents and RAG apps build their answers from search results. When a search
vendor quietly degrades — fewer relevant results, stale pages, a changed
ranking — everything on top of it degrades too. Vendors don't announce that.
SearchDrift does.

## What it does

- **Benchmarks vendors** on a versioned gold set of ~150 hand-written questions
  whose answers are settled and never change, so any score movement points at
  the vendor.
- **Two measurement tiers:**
  - **Tier 1 — direct vendor** (primary signal): a fixed query per question,
    raw results scored. No LLM in the loop, so a change can only come from the vendor.
  - **Tier 2 — agent in the loop** (secondary): an LLM agent chooses the queries.
- **Scores deterministically:** precision / recall / F1 with entity canonicalisation.
- **Detects drift honestly:** a frozen baseline, paired bootstrap confidence
  intervals, and Holm/BH multiple-comparison correction, with question count
  and repeats sized by a power analysis.
- **Records every external call** (cassettes) so any run replays for free.
  Development, tests and CI never touch the network.
- **Never overspends:** a credit ledger reserves budget in the same database
  transaction as the budget check, before any live call.

## How it works

```
            ┌──────────────────────┐
  client ──►│ API (control plane)  │  gold sets, runs, results — never calls vendors
            └──────────┬───────────┘
                       │ enqueue trials
                ┌──────▼──────┐        ┌───────┐
                │  PostgreSQL │        │ Redis │  distributed rate limiter
                │ queue · results · cassettes · ledger
                └──────▲──────┘        └───▲───┘
                       │ claim (SKIP LOCKED, leases, heartbeats)
            ┌──────────┴───────────┐       │
            │ workers × N          │───────┘
            │ (data plane)         │──► cassette layer ──► credit ledger ──► vendor APIs
            └──────────────────────┘──► LLM router (Gemini → Groq → Ollama)
```

- **Crash-safe queue on Postgres:** if a worker dies mid-trial, its lease
  expires and another worker picks the trial up. Unique constraints and
  cassettes make re-execution idempotent — no double results, no double charges.
- **LLM router:** every LLM call goes through one gateway with a fallback chain,
  retries, per-provider circuit breakers, token/cost accounting, and the model
  version requested vs. actually served.
- **Provenance on every run:** gold-set version, prompt version, model versions,
  full config, code version.

## Stack

Python 3.12 · FastAPI · SQLAlchemy 2.0 (async) · asyncpg · Alembic · PostgreSQL ·
Redis · httpx · pytest · Docker Compose · OpenTelemetry + Prometheus/Grafana

