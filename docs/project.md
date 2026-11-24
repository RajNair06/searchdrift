# SearchDrift — What the Project Is

> Start here. This doc explains what SearchDrift does and why, and lists the
> entities (the "things" the system stores). Each entity gets its own deep-dive
> doc later in `docs/entities/`, one at a time, when we build it.
> The schedule is in [plan.md](plan.md).

---

## 1. The problem, in one paragraph

AI agents and RAG apps don't know things on their own. They call a **search API**
(Tavily, Exa, Serper, …) and build their answer from what comes back. If that
search API quietly gets worse — fewer relevant results, stale pages, a changed
ranking — every app on top of it gets worse too, and nobody notices until users
complain. Vendors don't publish "our quality dropped 4% on Tuesday".

**SearchDrift measures search vendors over time and tells you when one of them
really changed.**

## 2. The one sentence the system must be able to say

> "On **this frozen question set**, measured **this way**, vendor **X** scored
> **0.71 ± 0.03**. Compared to its baseline, it **dropped by 0.06**, and that
> drop is **bigger than its normal noise** (statistically significant after
> correction)."

Every part of the system exists to make one word of that sentence trustworthy:

| Word in the sentence | What makes it trustworthy | Built in |
|---|---|---|
| "frozen question set" | A versioned gold set that never changes after freezing | Week 1 |
| "measured this way" | Recorded provenance: which query, which config, which model | Weeks 1, 4 |
| "scored 0.71" | Deterministic scoring against known correct answers | Week 2 |
| "± 0.03" / "bigger than noise" | Repeats, bootstrap confidence intervals, paired tests | Week 5 |
| (implicit) "and it didn't cost a fortune" | Cassettes (record/replay) + a credit ledger | Weeks 1–2 |
| (implicit) "and a crash didn't corrupt it" | A crash-safe job queue | Week 3 |

## 3. How a measurement works (the core loop)

Think of it like a school exam for search engines.

1. **Write the exam.** We hand-write questions and their correct answers.
   This is the **gold set**. Then we **freeze** it so it can't change.
2. **Give the exam.** We start a **run**: "ask every question to every vendor,
   3 times each". Each single (question × vendor × repeat) is one **trial**.
3. **Grade it.** For each trial we compare what the vendor returned against
   the correct answers and compute precision / recall / F1.
4. **Compare to last time.** We compare this run to a frozen **baseline** run.
   If the score moved more than normal noise, we raise a **drift** alert.

### Two ways to "give the exam" (tiers)

| | Tier 1 — direct vendor | Tier 2 — agent in the loop |
|---|---|---|
| Who writes the search query | We do (a fixed query per question) | An LLM agent decides |
| Noise | Low — only the vendor can change | Higher — the LLM adds its own randomness |
| Purpose | **Primary drift signal** | Secondary: "how good is this vendor *for an agent*?" |
| Built in | Week 2 | Week 4 |

Why Tier 1 is primary: if you measure through an agent and the score drops,
you can't tell if the **vendor** got worse or the **LLM** behaved differently.
Tier 1 removes the LLM, so a change can only come from the vendor (or the world).

## 4. What the system is NOT

- Not a search engine. It never answers user questions.
- Not an LLM benchmark. LLMs are tools inside Tier 2, not the thing measured.
- Not real-time monitoring. It runs on a schedule (nightly) within a credit budget.

## 5. The big constraints (why the design looks the way it does)

1. **Vendor calls cost money** and free tiers are small (~1,000 calls/month).
   → Every call is **recorded** (cassette) so we can replay it for free, and every
   live call goes through a **budget check** (credit ledger) first.
2. **The world changes.** A correct answer today can be wrong next month.
   → v1 uses only **stable** questions: answers settled for at least a year that
   never change. (Measuring *freshness* with recent-event questions is deferred
   until after the MVP — see `entities/Question.md` §4.)
3. **Processes crash.** A run is hundreds of trials; a worker can die mid-way.
   → Trials live in a **Postgres job queue** with leases, so a dead worker's
   trials get picked up again, and nothing is scored or charged twice.

---

## 6. The entities

An **entity** is a kind of thing the system needs to *remember* — something with
an identity that we store in a database table and refer to later.

A useful test: *"If the process restarts, do I need this to still exist?"*
If yes, it's probably an entity. If no, it's just code.
(Example: the Redis rate limiter's token counts are **not** an entity — if they
are lost, nothing bad happens; they refill in seconds.)

### 6.1 The map

```
                 ┌──────────┐
                 │  Vendor  │  Tavily / Exa / Serper (+ monthly budget)
                 └────┬─────┘
                      │
┌──────────┐     ┌────┴─────┐     ┌──────────┐
│ GoldSet  │────<│   Run    │────<│  Trial   │──── one question × one vendor × one repeat
│ (v1, v2) │     └────┬─────┘     └────┬─────┘     (this table is also the job queue)
└────┬─────┘          │                │
     │                │           ┌────┴─────┐
┌────┴─────┐          │           │  Score   │  precision / recall / F1 for that trial
│ Question │──────────┼──────────>└──────────┘
│ (+ gold  │          │
│  answer) │     ┌────┴─────┐     ┌──────────────┐
└──────────┘     │ Baseline │────>│ DriftReport  │  "vendor X moved by Δ, p < α"
                 └──────────┘     └──────────────┘

Supporting (every external call passes through these):
  Cassette      one recorded request/response, keyed by a hash of the request
  LedgerEntry   one credit reservation for one live vendor call (reserved → settled / uncertain / released)
  LLMCall       one LLM call made by the router: provider, model requested vs. observed, tokens, cost

  ──<  means "one to many"   (one Run has many Trials)
```

### 6.2 One line per entity

Grouped by the job they do. "Problem" is which constraint from §5 (or the core
loop in §3) the entity exists for.

**Truth — what's the right answer?**

| Entity | What it is | Why it must exist | Week |
|---|---|---|---|
| **GoldSet** | A named, versioned collection of questions (`v1`, `v2`). Status: `draft` → `frozen`. | You can only compare two runs if they used the *exact same* questions. Freezing guarantees that. | 1 |
| **Question** | One exam question: its text (sent as-is to vendors in Tier 1), its scoring unit (`entities` or `urls`), and the gold answer. | It's the unit everything is scored on. | 1 |

**Instruments — what are we measuring?**

| Entity | What it is | Why it must exist | Week |
|---|---|---|---|
| **Vendor** | One search API we benchmark (name, adapter, cost per call, monthly budget). | Runs, trials, cassettes and ledger entries all need to say *which* vendor. Budget lives here. | 1 |

**Execution — giving the exam**

| Entity | What it is | Why it must exist | Week |
|---|---|---|---|
| **Run** | One execution of a gold set against some vendors: tier, repeats, mode (live/replay), status, provenance (gold-set version, config, code version, prompt/model version). | Groups trials so they can be scored and compared as one measurement. Provenance answers "measured *how*?". | 1 (provenance grows in week 4) |
| **Trial** | One (question × vendor × repeat) inside a run: status, raw vendor result, attempts, lease. | It's the smallest unit of work. In week 3 this table **becomes the job queue** — workers claim trials from it. | 1 (lease fields in week 3) |
| **Score** | The deterministic score of one trial: precision, recall, F1, plus which gold items were matched. | Keeps "what the vendor said" (Trial) separate from "how we graded it" (Score), so we can re-grade without re-calling the vendor. | 2 |

**Cost & reproducibility — protecting the budget**

| Entity | What it is | Why it must exist | Week |
|---|---|---|---|
| **Cassette** | One recorded external call: request hash (the key), request, response, when it was recorded. | Replaying a cassette is free and identical. Tests and CI run on cassettes only, with no network. | 1 |
| **LedgerEntry** | One credit reservation for one live call: vendor, amount, state (`reserved` → `settled` / `uncertain` / `released`). | Stops us going over budget, even with many workers at once. `uncertain` = "the call may have happened; don't charge twice." | 1 (minimal), 2 (full) |
| **LLMCall** | One LLM call from the router: provider, model requested vs. observed, tokens in/out, cost, latency, fell-back-or-not. | Tier 2 provenance and LLM cost accounting. | 4 |

**Drift — did it really change?**

| Entity | What it is | Why it must exist | Week |
|---|---|---|---|
| **Baseline** | A pointer saying "this run is the reference for vendor X on gold set vN". Frozen. | Drift is always *relative to something*. This is the something. | 5 |
| **DriftReport** | The result of comparing a run to its baseline, per vendor: Δ score, confidence interval, p-value, corrected p-value, flagged yes/no. | It's the product's output — what the leaderboard and alerts show. | 5 |

**Later / stretch** (not designed now): `JudgeVerdict` and `HumanLabel` (LLM
judge + calibration, week 6 stretch), attribution experiments (after January).

### 6.3 Things that look like entities but aren't (for now)

| Thing | Why it's not its own table yet |
|---|---|
| Gold answer | Stored inside **Question** (a JSON list of entities with aliases, or URLs). A frozen gold set never changes, so the answer doesn't need its own history. We split it out only if we find a reason. |
| Prompt version | A field on **Run** (a hash + name of the prompt file). Becomes a table only if we need to list/compare prompts. |
| Rate limiter state | Lives in Redis, is temporary, and is fine to lose. |
| Config | Stored as JSONB on the Run (`Run.config`). |

Rule we follow: **start with the fewest tables that work**; split an entity out
only when a real need shows up. Each split is a lesson.

---

## 7. Open questions (we answer these in the deep dives)

1. ~~**Precision for entity questions.**~~ **Settled** in `entities/Question.md`
   §5: precision is measured per result (a result is relevant if it mentions a
   gold entity or matches a gold URL), so it stays deterministic.
2. ~~**Fresh questions' answers go stale.**~~ **Settled** in `entities/Question.md`
   §4: v1 has no fresh questions; freshness is deferred until after the MVP.
3. **What exactly is hashed into a cassette key** (method, URL, body — but not
   the API key or timestamps). → **Cassette** deep dive.

## 8. Order of deep dives (one at a time)

Following the order we build them in week 1:

1. **Question** — the heart of the system; answers open questions 1 and 2.
2. **GoldSet** — versioning and freezing.
3. **Vendor** — the adapter interface and budget.
4. **Run** and **Trial**.
5. **Cassette**.
6. **LedgerEntry** (minimal version).
7. Week 2+: Score, then the rest as each week needs them.
