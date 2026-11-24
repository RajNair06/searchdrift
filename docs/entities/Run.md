# Run

> Status: **locked (2026-11-22)**. Built in week 1 (Tier 1, run by a local
> runner process); queue execution in week 3; Tier 2 + LLM provenance in week 4.

## 1. What it is

A **Run** is one sitting of the exam: "give GoldSet v1 to Tavily, Exa and
Serper, top 5 results, 3 repeats each, live". It records:

- **what** was measured — which frozen GoldSet, which vendors;
- **how** — the settings (k, repeats, live or replay, adapter options) and the
  code version;
- **how it went** — status, start and finish times, error.

The actual work is split into **Trials**, one per (question × vendor × repeat).
A Run with 50 questions × 3 vendors × 3 repeats has **450 trials**.

## 2. Why it exists

Every number SearchDrift publishes is a property of a Run: "Tavily scored 0.71
**in run X**". The Run answers the "measured *how*?" part of our core sentence.
Without it:

- you couldn't group 450 trial scores into one measurement;
- you couldn't tell whether two measurements are comparable (same exam, same
  settings, same code?);
- a drift alert couldn't say "compared to *which* earlier measurement".

## 3. How it fits the core loop

```
POST /runs {gold_set_id, config}                     (API — control plane)
   │  validate: GoldSet frozen? vendors enabled? budget enough?
   │  create Run (pending) + all its Trials, in ONE transaction
   ▼
runner process picks up the Run                      (data plane)
   │  status → running
   │  executes trials (vendor calls go through the cassette/ledger gate)
   │  scores each trial
   ▼
all trials finished → status → completed
   │
   ▼
later: a Run can be marked as a Baseline; other Runs are compared to it (week 5)
```

**The API never executes the run**, even in week 1. It only creates the Run and
its Trials. A separate **runner** process (a CLI command in weeks 1–2, N worker
processes from week 3) does the vendor calls. This is the control-plane /
data-plane split from day one: the process that accepts HTTP requests can
never spend credits. In week 3 the runner becomes workers without the API
changing at all.

## 4. Mode: live or replay

| Mode | What happens per vendor call | Used for |
|---|---|---|
| `live` | **Always** call the vendor (through the ledger), record the response as a new cassette | Real measurements: baselines, nightly runs |
| `replay` | Use the recorded cassette. **No cassette → the trial fails.** Never calls the network. | Dev, tests, CI, re-scoring old results (reproduces a named source run — Cassette.md §6) |

### Why there is no "replay if recorded, otherwise live" mode

It sounds convenient, but it's poison for measurement. A run in that mode
silently mixes **old** vendor responses (from cassettes, maybe weeks old) with
**new** ones. If Tavily changed last week, half the trials would show the old
Tavily and half the new one, and the run would measure neither.

Drift detection needs every trial in a run to reflect the vendor **now**, so
measurement runs are always fully `live`. Replay runs are for everything
that isn't a measurement. Two clean modes beat three muddy ones.

(Corollary: a `replay` run can never show drift — it replays the same
responses forever. That's exactly why it's perfect for tests.)

### The rule: measuring the vendor → live; measuring anything else → replay

- **The gold answer is never part of the request.** The vendor only sees the
  question text and settings; gold is used only when scoring. So "same
  question + same gold" is just "same request".
- **Repeats inside a live run are never replayed from each other.** Repeats
  exist to measure the vendor's own noise (ranking jitter, varying snippets).
  Replaying repeat #1 for #2 and #3 would make the measured noise zero, and
  week 5's statistics would then flag every normal wobble as drift.
- **Replay is right when the vendor is not what's being measured:** tests and
  CI (testing our code), re-grading after a `gold` fix in a new GoldSet version
  (same text → same request → replay and score against the new answer, zero
  credits), and re-scoring after a scorer fix.
- **Saving credits happens elsewhere:** fewer, scheduled live runs (week 7) and
  a question/repeat count sized by power analysis (week 5) — not by replaying
  inside a measurement.

## 5. Fields

| Field | Type | Null? | Why it exists | Week |
|---|---|---|---|---|
| `id` | UUID | no | Primary key. Trials, Scores, Baselines point at it. | 1 |
| `gold_set_id` | UUID, FK → gold_sets.id | no | Which exam. Must be **frozen** (checked at creation). Its `content_hash` is part of provenance, reachable through this FK; no need to copy it. | 1 |
| `config` | JSONB | no | All the settings, validated by a Pydantic model (§6). | 1 |
| `code_version` | TEXT | no | The git commit SHA the runner was built from. Adapters and the scorer are code: if they change, the measurement instrument changed. | 1 |
| `status` | TEXT, CHECK in (`pending`, `running`, `completed`, `failed`) | no | Where the run is in its life (§7). | 1 |
| `error` | TEXT | yes | Why it failed, if `status = failed`. | 1 |
| `created_at` | TIMESTAMPTZ, default now() | no | When it was requested. | 1 |
| `started_at` | TIMESTAMPTZ | yes | When the runner began. | 1 |
| `finished_at` | TIMESTAMPTZ | yes | When it ended. The leaderboard's "measured at" (its *freshness bound*) comes from here. | 1 |
| `prompt_version`, model provenance | — | — | Tier 2 only: which prompt the agent used. Models actually served are recorded per call in **LLMCall**. | 4 |

### Columns vs. the `config` JSON

A rule of thumb you'll reuse everywhere:

- **Columns** for things the database must **check, join or filter on**:
  `gold_set_id` (foreign key), `status` (CHECK + "show running runs"),
  timestamps.
- **JSONB** for a bag of settings that code reads as a whole and that we
  mostly store *for the record*. Adding a new setting then needs no migration.

## 6. The `config`

```json
{
  "medium": "none",
  "mode": "live",
  "vendors": ["tavily", "exa", "serper"],
  "k": 5,
  "repeats": 3,
  "adapters": {
    "tavily": {"search_depth": "basic"},
    "exa":    {"contents": "text"},
    "serper": {}
  }
}
```

| Setting | Meaning |
|---|---|
| `medium` | What sits between the question and the vendor. `"none"` (Tier 1: the question `text` goes straight to the vendor) in week 1; `"agent"` (Tier 2: an LLM agent writes the queries) arrives in week 4. Defaults to `"none"`. An explicit string, not `null`: in JSON and SQL a `null` can't be told apart from a missing field, and this is a deliberate choice that should be recorded as one. (Renamed from `tier`, 2026-11-23.) |
| `mode` | `live` or `replay` (§4). |
| `replay_from_run_id` | Required when `mode = replay`: the past run to reproduce. Each trial replays the cassette the matching source trial got (Cassette.md §6). |
| `vendors` | Which vendors to test. Each must exist and be `enabled`. |
| `k` | Results requested per call; the same for every vendor (fairness). |
| `repeats` | How many times each question is asked to each vendor. Repeats measure the vendor's own randomness — its **noise floor**. Week 5's power analysis picks the right number; 3 is a placeholder. |
| `adapters` | Per-vendor request options. Part of the instrument (they also change the cassette request hash). |

**No `config_hash` (decided 2026-11-22).** It would be derived data with no
job of its own: JSONB equality already ignores key order
(`WHERE config = '{…}'::jsonb`), and drift compares runs *per vendor* on a few
specific settings, which a whole-config hash can't answer. Which settings must
match is defined in the Baseline doc (week 5).

## 7. State machine

```
pending ──runner starts──► running ──all trials finished──► completed
   │                          │
   └──────────────────────────┴──run-level failure──► failed
```

| Status | Meaning |
|---|---|
| `pending` | Created with all its trials; nothing executed yet. |
| `running` | The runner is executing trials. |
| `completed` | Every trial reached a final state. **Some trials may have failed** (a vendor timed out); that's recorded per trial and reported, not hidden. |
| `failed` | The run as a whole couldn't continue: budget exhausted mid-run, vendor disabled, runner bug. `error` says why. |

Why does a failed trial not fail the run? Vendors time out sometimes; that's
part of what we measure (and a 0 score). Failing a 450-trial run because of
one timeout would waste the other 449 live calls we already paid for.
How many failed trials make a run unusable for drift is a week 5 question.

Week 3 adds `cancelled` (stop a run on purpose) when there are workers to stop.

## 8. Creating a run: validation, in one transaction

`POST /runs` with `{gold_set_id, config}`:

1. Validate `config` with Pydantic (types, `k ≥ 1`, `repeats ≥ 1`, known tier/mode).
2. GoldSet exists and is **frozen** — else `409`.
3. Every vendor exists and is **enabled** — else `422`.
4. **Live runs only:** budget pre-check. Calls needed per vendor =
   questions × repeats. If any vendor's remaining budget is smaller → `422`
   with the numbers. Fail fast, before spending anything, instead of running
   out halfway.
5. Insert the Run (`pending`) **and all its Trials** in the same transaction.

Why create all trials up front (step 5)? The run's scope is fixed the moment
it's created: progress is simply "finished trials / total trials", and in
week 3 those trial rows *are* the job queue. Same transaction → you never see a
run with half its trials.

Why is step 4 only a pre-check? Two live runs created at the same moment can
both pass it and together need more than the budget. The real guarantee comes
from the ledger reserving credits **per call** inside a transaction (week 2).
The pre-check just avoids obviously doomed runs.

## 9. API

| Method & path | What it does |
|---|---|
| `POST /runs` | Validate and create a Run + its Trials (§8). Returns the run and trial count. |
| `GET /runs` | List runs (filter by status, gold set). |
| `GET /runs/{id}` | One run, with progress: trial counts by status. Score summaries come with Score (week 2). |
| `POST /runs/{id}/cancel` | Week 3. |

## 10. Decisions to review

1. **Two modes only, `live` and `replay`** — no mixed mode (§4).
2. **Trials created up front**, in the same transaction as the Run.
3. **The API never executes runs**; a separate runner does, even in week 1.
4. **Failed trials don't fail the run**; only run-level problems do.
5. **`code_version` = git SHA**, covering adapter and scorer changes. (This
   replaces the "scorer version" mentioned in Question.md.)

## 11. Subtleties

- **Repeats and cassettes.** In `live` mode, the 3 repeats of one question are
  3 identical requests — same cassette key — but possibly 3 different
  responses. The cassette store must keep all of them, not overwrite. And in
  `replay` mode, which recording does repeat #2 get? → **Cassette** doc.
- **Double-click = double spend.** If a client sends `POST /runs` twice (a
  retry after a timeout), we create two live runs and spend twice. Fix:
  an `Idempotency-Key` header → week 3 (idempotency lesson). Until then, the
  budget pre-check limits the damage.
- **Which runs are comparable?** Same GoldSet + same per-vendor settings + same
  code version, at least. Exactly which fields must match (e.g. does `repeats`
  have to?) is decided in the **Baseline / DriftReport** docs (week 5).
- **Runner crash mid-run (weeks 1–2).** The run stays `running` forever and
  some trials are half-done. Weeks 1–2 accept this (restart by hand).
  Fixing it properly is exactly week 3's lesson: leases, heartbeats, reclaiming.
- **Re-scoring.** Because responses are stored (cassettes + trials), a
  `replay` run of an old run's config re-scores with new scorer code at zero
  cost — handy after fixing a scorer bug or a gold typo in a new GoldSet version.

## 12. Not in this version

| Idea | When |
|---|---|
| `cancelled` status, cancel endpoint | Week 3 |
| `Idempotency-Key` on `POST /runs` | Week 3 |
| `medium = "agent"`, `prompt_version` | Week 4 |
| Run name / purpose label ("nightly", "baseline") | Baselines are their own entity (week 5); a label can be added if the run list gets confusing. |
| Scheduled runs (nightly) | Week 7 |
