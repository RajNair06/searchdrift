# Trial

> Status: **locked (2026-11-22)**. Built in week 1; queue fields (lease,
> attempts) in week 3; Tier 2 changes in week 4.

## 1. What it is

A **Trial** is the smallest unit of work: **one question, asked to one vendor,
once** — "repeat 2 of *Who created Python?* on Tavily, in run X".

```
Run X: 50 questions × 3 vendors × 3 repeats
  ├── Trial: python-creator × tavily × 1
  ├── Trial: python-creator × tavily × 2
  ├── Trial: python-creator × tavily × 3
  ├── Trial: python-creator × exa    × 1
  └── ... 450 trials in total
```

In Tier 1, one trial = **exactly one vendor call**.

## 2. Why it exists

- **It's the unit of execution.** The runner works trial by trial. If the
  runner dies at trial 301, trials 1–300 are done and saved; we know exactly
  what's left.
- **It's the unit of evidence.** Each trial links to the vendor response it
  got (a Cassette). That's the chain behind every score:
  `Score ← Trial → Cassette (what the vendor said) + Question (what we asked)`.
- **It's the unit of failure.** A timeout is recorded on that one trial; the
  other 449 are unaffected.
- **In week 3, this table becomes the job queue.** Workers claim `pending`
  trials straight from it. No separate queue system — that's why trials are
  created up front with the Run.

## 3. How it fits the core loop

```
POST /runs ──► Run + 450 Trials created (all pending)
                          │
runner, for each pending trial:
   status: pending → running
   request = adapter.build_request(question.text, k)
   gate: cassette (replay) or ledger + live call + record (live)
      ├─ got a response that parses   → cassette_id set, status → succeeded
      └─ timeout / HTTP error / ...   → error_kind + error set, status → failed
                          │
scorer: for each succeeded trial
   results = adapter.parse_response(cassette.response)
   Score = compare(results, question.gold)      (week 2)
```

## 4. Fields

| Field | Type | Null? | Why it exists | Week |
|---|---|---|---|---|
| `id` | UUID | no | Primary key. Scores point at it. | 1 |
| `run_id` | UUID, FK → runs.id | no | Which run it belongs to. | 1 |
| `question_id` | UUID, FK → questions.id | no | What we asked. | 1 |
| `vendor_id` | TEXT, FK → vendors.id | no | Whom we asked. | 1 |
| `repeat_index` | INTEGER, ≥ 1 | no | Which repeat (1, 2, 3). Separates the three otherwise-identical trials. | 1 |
| `status` | TEXT, CHECK (see §5) | no | Where it is in its life. Default `pending`. | 1 |
| `cassette_id` | UUID, FK → cassettes.id | yes | The exact vendor response this trial got (recorded in live mode, or replayed). Always set when `succeeded`; also set when `failed` with an HTTP error response (the error response is recorded too — Cassette.md §8). | 1 |
| `error_kind` | TEXT, CHECK (see §6) | yes | Short, fixed category of failure, so we can count them. Set when `failed`. | 1 |
| `error` | TEXT | yes | The detail: `"timeout after 10s"`, `"HTTP 503"`. For humans debugging. | 1 |
| `attempts`, `lease_owner`, `lease_expires_at` | — | — | Retries and crash recovery — the job-queue fields. | 3 |

**Constraints**

- `UNIQUE (run_id, question_id, vendor_id, repeat_index)` — a run can never
  contain the same trial twice. Week 3's guarantee "every trial ends up with
  exactly one result" starts here: duplicates are impossible at the database
  level, not just "unlikely in our code". It also indexes "all trials of run X".
- `CHECK (status <> 'succeeded' OR cassette_id IS NOT NULL)` — a success
  always has evidence.
- `CHECK ((status = 'failed') = (error_kind IS NOT NULL))` — failed ⇔ has a
  failure category.

### What is deliberately NOT stored on the trial

| Not stored | Where instead | Why |
|---|---|---|
| Parsed results (`list[SearchResult]`) | Computed: `adapter.parse_response(cassette.response)` | Parsing is a pure function of the stored raw response, so storing its output would be a second copy of the same fact. Bonus: fix a parser bug and every old trial re-parses correctly. |
| Latency | On the Cassette | Latency is a property of the vendor call. A replayed trial has no real latency of its own; it reuses the recorded one. |
| Score | Score table (week 2) | Keeps "what the vendor said" apart from "how we graded it", so re-grading never touches trials. |
| Timestamps | — | Not needed for week 1; week 3 adds lease timestamps. |

## 5. State machine

```
           runner claims               response OK
 pending ───────────────► running ─────────────────► succeeded
    │                        │
    │                        └── no usable response ──► failed
    │
    └── run aborted (budget, kill switch, ...) ──► skipped
```

| Status | Meaning | Final? |
|---|---|---|
| `pending` | Waiting to be executed. In week 3: "a worker may take this". | no |
| `running` | A runner is executing it right now. | no |
| `succeeded` | Got a vendor response that parsed. **0 results is still a success** — the vendor answered "nothing", which scores 0. | yes |
| `failed` | No usable response (§6). | yes |
| `skipped` | Never attempted because the run was aborted. The reason is in `Run.error`. | yes |

This answers what we left open in the Run doc: when a run aborts, its
unfinished trials become `skipped`, so nothing sits at `pending` looking like
work to do — which matters a lot once workers poll for `pending` in week 3.

### Every status change is a guarded update

```sql
UPDATE trials SET status = 'running'
WHERE id = :id AND status = 'pending';      -- 1 row updated = we own it
```

The `AND status = 'pending'` means: "move it to running *only if nobody else
already did*". If the update touches 0 rows, someone else got there first.
With one runner in week 1 this never happens, but it's free to write this way,
and it's the seed of week 3's worker claim (`FOR UPDATE SKIP LOCKED`).

## 6. Failure kinds: whose fault was it?

| `error_kind` | Example | Whose fault? | Scoring (decided in Score doc) |
|---|---|---|---|
| `timeout` | No answer within 10 s | Vendor | Probably counts as 0: slowness is part of vendor quality |
| `http_error` | 500, 503, 429 | Vendor (mostly) | Probably counts as 0 |
| `parse_error` | Response shape our adapter doesn't understand | **Us** (or a vendor API change) | Excluded and investigated |
| `replay_miss` | Replay mode, no cassette for this request | **Us** | Excluded; never happens in a valid replay |

Why a fixed category and not just the error text? Two reasons:

1. **Fairness.** Vendor failures are part of what we measure (a vendor that
   times out 5% of the time *is* worse). Our own bugs are not, and must never
   lower a vendor's score. The category tells the scorer which is which.
2. **Counting.** "Exa's timeout rate this week" is
   `COUNT(*) WHERE error_kind = 'timeout'`. Counting free text doesn't work.

A note on `parse_error`: if a vendor changes its response format, our adapter
fails to parse. That's *a vendor change* we should notice loudly — but it's an
adapter fix, not a score of 0. A spike in `parse_error` is an alert in itself.

## 7. Subtleties

- **0 results ≠ failure.** An empty result list is a valid answer, scored 0.
  A failure means we never got an answer. Mixing them up would either hide
  vendor outages or punish honest "no results".
- **Runner crash (weeks 1–2).** A trial left in `running` stays there forever.
  Week 3's fix: a lease (`lease_expires_at`); if the worker stops renewing it,
  the trial goes back to `pending` for someone else.
- **Retrying a failed call (week 3).** A retry creates no new trial: the same
  trial is attempted again (`attempts` + 1). Otherwise the unique constraint
  and the "one result per trial" rule would break.
- **Tier 2 breaks "one trial = one call" (week 4).** An agent may search 3
  times for one question, so a trial will link to *several* cassettes and LLM
  calls. A single `cassette_id` won't fit then; we'll migrate when we get there
  — a real schema-evolution lesson.
- **Scale.** 450 trials per run, one live run a night → ~160,000 rows a year.
  Tiny for Postgres. Week 5 looks at what *does* hurt queue tables: frequent
  status updates leave dead row versions behind (MVCC bloat).

## 8. API

Trials are read through their run; nobody creates or edits them by hand.

| Method & path | What it does |
|---|---|
| `GET /runs/{id}/trials` | List trials of a run (filter by status, vendor, question). |
| `GET /trials/{id}` | One trial, with its question, vendor and parsed results. |

## 9. Decisions to review

1. **Store the cassette link, not the parsed results** — parse on demand.
2. **`error_kind` separates vendor faults from our faults**, so our bugs never
   lower a vendor's score.
3. **`skipped`** for trials of an aborted run.
4. **0 results = `succeeded`** (scored 0), not `failed`.

## 10. Not in this version

| Idea | When |
|---|---|
| `attempts`, leases, heartbeats | Week 3 |
| Several calls per trial (agent) | Week 4 |
| Timestamps (`started_at`, `finished_at`) | Week 3, with leases |
