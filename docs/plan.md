# 8-Week Plan: Backend + Applied AI Engineer via SearchDrift

**Dates:** Nov 23, 2026 – Jan 17, 2027

## Context

**Goal:** be ready to interview for applied-AI / backend / AI-infra internships or junior roles at startups in 8 weeks.

**Starting point:** has built a few APIs. Working full-time on this (8+ hrs/day). Python only. Light daily DSA.

**Approach:** SearchDrift is the only project, and you learn as you build. Each week's fundamentals are the ones that week's milestone needs. A separate daily theory block covers breadth the project won't naturally reach (system design, networking). The Sunday self-test makes sure you actually learned the concepts, not just shipped code.

Startups hiring for this role want three things:

1. Proof that you can ship a production LLM system: evals, observability, cost and latency control, failure handling.
2. Backend depth: databases, concurrency, caching, queues, system design.
3. Something real in public: a deployed project, a README and design doc, blog posts, a demo video.

SearchDrift hits all three.

## Daily structure (~9 hrs)

| Block  | Time           | What |
|--------|----------------|------|
| DSA    | 1 hr (morning) | NeetCode 150 patterns: about 2 problems a day, 110+ by the end |
| Theory | 2–2.5 hrs      | That week's Fundamentals to master plus reading |
| Build  | 5 hrs          | That week's SearchDrift milestone |
| Log    | 15 min         | Public learning log (turn these into blog posts later) |

**Sundays:** half day. Explain each item on that week's fundamentals list without notes; anything you can't explain carries over to next week. Do one system-design mock every Sunday from week 3 on.

---

## SearchDrift — 8-week MVP scope

**Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0 (async), asyncpg, Alembic, Postgres, Redis, httpx, pytest, Docker Compose, OpenTelemetry + Prometheus/Grafana.

- **Gold set v1:** about 150 questions, stable only (answers settled for at least a year), for drift detection. Versioned. *(Changed 2026-11-22: fresh questions for measuring freshness moved to after the MVP — see `entities/Question.md` §4.)* Each question has a defined scoring unit: answer entities or relevant URLs, depending on its type.
- **3 vendors** (e.g. Tavily, Exa, Serper) behind one adapter interface. Pick based on free-tier limits.
- **Two measurement tiers:**
  - Tier 1, direct vendor (the primary drift signal): fixed query → raw results → scored. No agent noise.
  - Tier 2, agent-in-the-loop (secondary): an LLM agent picks queries and tools.
- **Cassette layer:** every external call is recorded, keyed by a request hash. Replay mode is the default in dev, tests and CI.
- **LLM router module:** an internal gateway for every LLM call.
  - Fallback chain: Gemini → Groq → Ollama
  - Retries with backoff and a circuit breaker per provider
  - Per-call token and cost accounting
  - Records the model version requested vs. observed
- **Distributed rate limiter (Redis):** per-vendor and per-provider limits, shared across N workers.
- **Postgres job queue:** control-plane API plus N workers. Workers claim jobs with `FOR UPDATE SKIP LOCKED` and hold leases with heartbeats, so a crashed worker's trials get picked up again. Re-execution is idempotent, enforced by unique constraints plus the cassettes.
- **Credit ledger:** checks the per-vendor budget inside the same transaction that reserves credits, before any live call. Calls with an unknown outcome are recorded as uncertain and never charged twice.
- **Deterministic scoring:** precision / recall / F1, with entity canonicalisation.
- **Drift detection:** a frozen baseline, paired bootstrap confidence intervals, and Holm/BH correction. A power analysis sizes the question count and repeats.
- **Provenance on every run:** gold-set version, prompt version, model version requested vs. observed, and config hash. *(2026-11-22: stored as the full config + code version instead of a hash — see `entities/Run.md`.)*
- **Observability:** OTel trace per trial. Metrics for queue depth, lease expiries, spend per vendor, p50/p99 latency, and fallback rate.
- **Public leaderboard page:** per-vendor scores with confidence intervals, a freshness bound, and drift alerts. Deployed, with a nightly run inside the budget.
- **Stretch goal:** LLM judge as a secondary score, calibrated against about 100 of your own labels and reporting Cohen's kappa. Plus a prompt-injection test suite over vendor results.
- **After January:** freshness measurement (fresh, time-anchored questions), attribution experiments, the synthetic-question research pipeline (position bias, tool-choice consistency), and statistically gated self-improvement.

---

## Week-by-week

### Week 1 — Networking, Python concurrency, project skeleton

- **Fundamentals to master:**
  - Networking: TCP 3-way handshake and teardown, HTTP/1.1 vs HTTP/2 (multiplexing, head-of-line blocking), TLS handshake, DNS resolution path, WebSockets vs SSE
  - Python concurrency: asyncio event loop, the GIL, threads vs processes vs async and when each fits, I/O models (blocking, non-blocking, epoll), httpx connection pooling and timeouts
  - REST API design, auth (JWT vs sessions, API keys)
- **Reading:** the asyncio docs, Fluent Python (concurrency chapters), the FastAPI docs (async, dependencies), the httpx docs.
- **Build:** repo, Docker Compose (Postgres + Redis), FastAPI app, Alembic schema v1 (benchmarks, gold questions, runs, trials, results, cassettes, ledger), httpx adapters for 3 vendors, cassette record/replay layer, pytest and CI running on replay only. Write the first 50 gold questions, with a scoring unit defined per question type.
- **Deliverable:** query all 3 vendors live once (recorded), then the whole test suite passes in CI with zero network access.

### Week 2 — Databases (applied), transactions, Redis

- **Fundamentals to master:**
  - Indexing strategy (B-tree, GIN, BRIN, composite and covering indexes), reading `EXPLAIN ANALYZE`
  - Transactions, isolation levels and their anomalies (dirty read, non-repeatable read, phantom, write skew), MVCC in Postgres, `SELECT … FOR UPDATE`
  - N+1 queries, connection pooling (asyncpg pool, pgbouncer, pool sizing)
  - Redis data structures, Lua scripts and atomicity, cache patterns (cache-aside, write-through, TTLs, stampede protection), token bucket vs sliding window
- **Reading:** DDIA ch. 1–3 (2nd ed. if available), the Postgres docs on transaction isolation, MVCC and indexes.
- **Build:** the credit ledger (reserve inside a transaction, settle afterwards, the uncertain state), deterministic scoring with entity canonicalisation, the Tier-1 runner (in-process for now), and the Redis distributed rate limiter per vendor. Grow the gold set to 100.
- **Deliverable:** a concurrency test where 50 parallel reservations never exceed the budget (and an explanation of which isolation level or locking makes that true). Plus a first scored Tier-1 run across 3 vendors.

### Week 3 — Distributed systems + the crash-safe queue

- **Fundamentals to master:**
  - CAP and PACELC, replication (leader/follower, replication lag, read-your-writes), partitioning/sharding, consistent hashing
  - Idempotency keys, at-least-once delivery, why exactly-once is a myth (and what "effectively once" means), outbox pattern, sagas
  - Leases, heartbeats, visibility timeouts, fencing tokens. Leader election and Raft at a conceptual level
  - Load balancers: L4 vs L7, health checks
- **Reading:** DDIA ch. 5–9, the Raft visualization (raft.github.io), Kleppmann's "How to do distributed locking". Read how libraries like river and pgmq implement Postgres queues.
- **Build:** split into a control-plane API plus N workers. Postgres queue with SKIP LOCKED, leases and heartbeats, reclaiming expired leases, idempotent trial execution (unique constraints plus cassettes), and graceful shutdown.
- **Deliverable:** a chaos test. Kill workers at random mid-run: every trial ends up with exactly one result, and the ledger is never double-charged. Write blog post #1, e.g. "A crash-safe job queue on Postgres, and the bugs I hit".

### Week 4 — Applied LLM engineering + the LLM router

- **Fundamentals to master:**
  - AI: tokens and tokenization, context windows, embeddings, structured outputs, prompt caching, tool-use loops (plan → act → observe), stop conditions
  - Prompt injection: why vendor results are untrusted input, and mitigations
  - Resilience patterns: retries with jittered backoff, circuit breakers, timeouts and deadline propagation, fallbacks, bulkheads
  - Retrieval and search metrics: precision, recall, F1, recall@k, MRR, nDCG. RAG failure modes downstream consumers hit (retrieval misses, stale results, conflicting sources)
- **Reading:** Chip Huyen, *AI Engineering* (key chapters). Anthropic's "Building effective agents". The Gemini and Groq API docs (rate limits, model versioning).
- **Build:** the LLM router module (fallback chain, circuit breaker, cost accounting, requested vs. observed model version), the Tier-2 agent-in-the-loop runner, and provenance recorded on every run.
- **Deliverable:** Tier-2 runs complete even when you force the primary provider to fail. Provenance shows which model actually served each call.
- **Start applying this week**, with SearchDrift's repo, README and blog post #1.

### Week 5 — Statistics for evals + DB internals

- **Fundamentals to master:**
  - Statistics: paired vs. unpaired tests, bootstrap confidence intervals, statistical power and sample size, multiple-comparison correction (Bonferroni, Holm, BH), false-positive rate
  - Postgres internals: heap pages and tuples, how MVCC stores versions, VACUUM and dead tuples (and why queue tables churn them), the WAL and crash recovery, the buffer pool, B+tree vs LSM-tree tradeoffs
- **Reading:** CMU 15-445 lectures (storage, buffer pool, indexes, concurrency control, recovery). Anthropic's write-up on adding error bars to evals ("A statistical approach to model evaluations"). *Database Internals* (Petrov), part I, as a reference.
- **Build:** freezing a baseline, a power analysis that fixes question count and repeats, paired bootstrap drift detection with Holm/BH correction, and per-question plus aggregate drift reports. Grow the gold set to 150. Investigate queue-table bloat with `pg_stat_user_tables` and tune autovacuum.
- **Deliverable:**
  - An injected synthetic regression is detected.
  - Re-running an unchanged config is not flagged as drift.
  - A short note on the queue bloat you measured and how you fixed it.

### Week 6 — Observability, evals depth, inference serving

- **Fundamentals to master:**
  - Observability: logs vs. metrics vs. traces, the RED/USE methods, histograms and percentiles (why you shouldn't average p99s), SLOs
  - AI evals: LLM-as-judge design, calibration against human labels, agreement metrics (Cohen's kappa), judge bias (position, verbosity), hallucination mitigation, cost/latency tradeoffs
  - Inference serving: KV cache, continuous batching, PagedAttention/vLLM, quantization basics, speculative decoding, GPU memory math
- **Reading:** the vLLM/PagedAttention paper, Hamel Husain's posts on evals and LLM judges, the OpenTelemetry Python docs.
- **Build:** OTel traces per trial, Prometheus metrics and a Grafana dashboard, and a local Ollama/vLLM fallback benchmarked for throughput and latency. Stretch: the calibrated LLM judge and the prompt-injection test suite.
- **Deliverable:** a dashboard screenshot for the README, and a vendor comparison table covering quality with confidence intervals, latency, and cost per query.

### Week 7 — System design (HLD + LLD) + ship

- **Fundamentals to master:**
  - HLD framework: requirements → estimates → API → data model → high-level design → deep dives → bottlenecks
  - HLD breadth the project doesn't cover: chat systems, news feeds, notification systems, URL shorteners, CDNs, sharding strategies
  - LLD: SOLID, common patterns (adapter for vendors, strategy for scorers, circuit-breaker state machine — all already in SearchDrift), and practice in code: LRU cache, rate limiter, parking lot
  - AI system design: "design ChatGPT", "design a RAG system for 10M docs", "design an LLM gateway", "design an eval platform" (SearchDrift)
- **Reading:** Alex Xu, *System Design Interview* vol. 1. Hello Interview write-ups.
- **Build:** deploy (Fly.io/Railway/VPS), a scheduled nightly run inside the budget, the public leaderboard page, DESIGN.md, and a 2–3 minute demo video.
- **Deliverable:** SearchDrift live. Write blog post #2, e.g. "Is your search API getting worse? Detecting real drift vs. noise", with real numbers. It's also strong outreach material for search-API and agent companies.
