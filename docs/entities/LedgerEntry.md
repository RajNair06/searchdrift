# LedgerEntry

> Status: **locked (2026-11-23)**. Table + reserve/resolve flow built in
> week 1 (one runner); proven safe under concurrency in week 2; retries
> (`attempt`) in week 3.

## 1. What it is

A **LedgerEntry** is **one live vendor call, written down in the books**:
"trial T reserved 1 Tavily credit; the call succeeded, so it was spent".

Every live call gets exactly one entry, created **before** the call and
resolved **after** it. Replay runs never touch the ledger, because replay is free.

## 2. Why it exists

Free credits are scarce and one-time for Exa and Serper. Once spent, they're
gone. We need two guarantees:

1. **Never overspend.** Before *every* live call, check that budget remains,
   and make that check impossible to bypass.
2. **Know what was spent, honestly**, including calls whose outcome we can't know.

### Why not just a counter (`vendors.spent = spent + 1`)?

A counter can only say "spent" or "not spent". The hard case needs a third answer:

> We sent the request to Exa. 10 seconds pass, no answer, timeout.
> **Did Exa process it and charge us?** Maybe. We can't know.

A counter forces a lie either way: `+1` (maybe charged for nothing) or `+0`
(maybe silently overspending). A ledger can record **"uncertain"**, which is
honest. It also tells you *which* trial spent *what*, which a single number
can't. And "spent so far" is computed from the entries (one source of truth,
Vendor.md §4).

## 3. How it fits the core loop: reserve → call → resolve

```
Trial in live mode
   │
   ▼
① RESERVE  (one short DB transaction)
   lock the vendor row; check enabled + budget; INSERT entry (reserved)
   │   no budget / disabled → don't call; run aborts (Run.error), trials skipped
   ▼
② CALL the vendor over HTTP           ← NO database transaction open here
   │
   ▼
③ RESOLVE  (another short transaction)
   UPDATE entry: reserved → settled | released | uncertain
```

**Why reserve *before* the call?** If we only wrote down the spend *after*
the call, a crash in between (call made, credit spent, nothing written)
would leave a spend with no record. Reserving first means the books are never
behind reality. At worst they're cautiously ahead.

**Why no transaction open during the call?** A vendor call takes 0.5–10
seconds. A transaction held that long keeps the vendor row locked, so every
other worker trying to reserve for that vendor waits for a network call.
Rule for life: **never hold a database transaction open across a network
call.** Hence two short transactions with the call in between.

## 4. States

```
               response, charged          
 reserved ─────────────────────────► settled     (final)
    │
    ├── request provably never processed ──► released   (final)
    │
    └── can't know ──► uncertain ──(manual check)──► settled | released
```

| State | Meaning | Counts against budget? |
|---|---|---|
| `reserved` | Credit held; call about to happen or in flight. | ✅ |
| `settled` | Call happened and was (or should be assumed) charged. | ✅ |
| `released` | Call provably not charged; credit given back. | ❌ |
| `uncertain` | We can't know if it was charged. | ✅ (cautious) |

**Rule: when unsure, count it.** Our budget is a cap *below* the real free
tier (Vendor.md §6). Counting a call that wasn't charged wastes a little of
that margin. Not counting one that *was* charged can push us past the real
limit. So mistakes always go in the safe direction.

### Which outcome leads to which state

| What happened | State | Why |
|---|---|---|
| 2xx response | `settled` | It worked; it cost a credit. |
| Couldn't connect at all (DNS failure, connection refused, **connect** timeout) | `released` | The request never left our machine, so the vendor never saw it. |
| 400 / 401 / 429 response | `released` | Rejected before any search was done (bad request, bad key, rate limited). *Verify per vendor when building; if a vendor charges for these, change to `settled`.* |
| 5xx response | `uncertain` | The vendor may have done the work and then failed. |
| **Read** timeout / connection dropped after sending | `uncertain` | The request arrived; we never learned the outcome. |

Notice the line between `released` and `uncertain`: **did the request
leave our machine?** That's why httpx has *separate* connect and read
timeouts (a week 1 fundamental). A connect timeout means "never sent", and a
read timeout means "sent, no answer". They must be handled differently.

### Resolving `uncertain`

Uncertain entries stay counted until you check the vendor's dashboard (most
show usage) and resolve them by hand: `PATCH /ledger/{id}` → `settled` or
`released`. Only `uncertain` can be changed this way. If the trial is retried
later (week 3), the retry gets its **own** entry: the uncertain call stays
counted once, the retry is counted once, and no call is ever counted twice.

## 5. Fields

| Field | Type | Null? | Why it exists | Week |
|---|---|---|---|---|
| `id` | UUID | no | Primary key. | 1 |
| `vendor_id` | TEXT, FK → vendors.id | no | Whose budget. Budget is per vendor. | 1 |
| `trial_id` | UUID, FK → trials.id | no | Which trial made the call. **Not nullable on purpose**: every live call must belong to a trial, so there's no side door for "quick manual test calls" that skip the books. | 1 |
| `state` | TEXT, CHECK in (`reserved`, `settled`, `released`, `uncertain`) | no | §4. | 1 |
| `created_at` | TIMESTAMPTZ, default now() | no | When it was reserved. Decides which budget period it belongs to (this month's Tavily budget). | 1 |
| `resolved_at` | TIMESTAMPTZ | yes | When it left `reserved`. An entry still `reserved` after minutes means the runner died mid-call (§7). | 1 |
| `attempt` | INTEGER | — | Which attempt of the trial (retries). | 3 |

**Constraints & index**

- `UNIQUE (trial_id)` in weeks 1–2 → becomes `UNIQUE (trial_id, attempt)` in
  week 3. Running the same trial twice by mistake **can't** reserve twice;
  the database refuses the second insert.
- `CHECK ((state = 'reserved') = (resolved_at IS NULL))`.
- Index on `(vendor_id, created_at)`: the budget check counts one vendor's
  entries in the current period on every live call, so it must be fast (a
  week 2 indexing exercise: check it with `EXPLAIN ANALYZE`).

**Not stored:** an amount. Each entry is one call = one credit (Vendor.md
§4). Add `credits` if a vendor mode ever costs more.

## 6. The reserve step in detail

```sql
BEGIN;
  SELECT enabled, budget_calls, budget_period
  FROM vendors WHERE id = 'tavily'
  FOR UPDATE;                              -- lock this vendor's row

  SELECT count(*) FROM ledger_entries
  WHERE vendor_id = 'tavily'
    AND state IN ('reserved', 'settled', 'uncertain')
    AND created_at >= <start of period>;   -- month start, or forever for 'total'

  -- enabled AND count < budget_calls ?  →
  INSERT INTO ledger_entries (vendor_id, trial_id, state) VALUES ('tavily', :t, 'reserved');
COMMIT;
```

**Why `FOR UPDATE` on the vendor row?** This is the week 2 deliverable in
miniature. Without it, two workers can interleave like this:

```
worker A: count → 599 (budget 600)   ✔ room for one
worker B: count → 599                ✔ room for one
worker A: INSERT  → 600
worker B: INSERT  → 601              ✘ over budget
```

Both read the same count before either wrote. Locking the vendor row makes
the second worker **wait** until the first commits; then it counts 600 and
stops. Week 1 has a single runner, so this can't happen yet, but we write it
correctly from the start. In week 2 you prove it with 50 parallel
reservations, and you'll learn *why* Postgres's default isolation level
(Read Committed) doesn't prevent this on its own.

## 7. Subtleties

- **Runner crash between reserve and resolve.** The entry stays `reserved`
  forever and keeps counting (safe direction). Weeks 1–2: on restart, mark old
  `reserved` entries as `uncertain` by hand. Week 3: the lease reaper does it
  automatically.
- **Our count vs the vendor's count.** They will drift apart a little
  (uncertain calls, manual tests in the vendor's playground). The vendor's
  dashboard is the truth about money; the ledger is our cautious estimate.
  Check them against each other now and then.
- **Monthly periods use calendar months** while Tavily resets on the billing
  date. The margin in our budget absorbs it.
- **The pre-check in `POST /runs` (Run.md §8) is not the guarantee.** This
  per-call reservation is.
- **Kill switch is checked here too.** Flipping `enabled = false` stops the
  very next reservation, even in the middle of a run.

## 8. API

| Method & path | What it does |
|---|---|
| `GET /ledger` | List entries (filter by vendor, state, period). |
| `PATCH /ledger/{id}` | Resolve an `uncertain` entry → `settled` or `released`. Any other change → `409`. |
| (`GET /vendors`) | Shows spent / remaining per vendor, computed from here. |

## 9. Decisions to review

1. **Reserve before, resolve after**, two short transactions, nothing held during the call.
2. **Four states**, including `uncertain`; **when unsure, count it**.
3. **Connect failure → released; read timeout / 5xx → uncertain.**
4. **Every live call belongs to a trial** (`trial_id` NOT NULL), so there are no side doors.
5. **Lock the vendor row** to make check-and-reserve atomic.
6. **State is updated in place** (with guarded updates `WHERE state = 'reserved'`).
   A strict accounting ledger would be append-only (a new row per change). We
   chose simplicity, because the four states are enough history for us.

## 10. Not in this version

| Idea | When |
|---|---|
| Concurrency proof (50 parallel reservations) | Week 2 |
| `attempt`, automatic reaping of stuck `reserved` entries | Week 3 |
| LLM token/cost accounting | Week 4, in **LLMCall** (LLMs are free-tier, rate-limited, not credit-capped) |
| Budget per phase / per run | Only if one vendor-wide cap proves too coarse |
