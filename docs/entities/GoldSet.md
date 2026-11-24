# GoldSet

> Status: **locked (2026-11-22)**. Built in week 1.

## 1. What it is

A **GoldSet** is one **version** of the exam: a named, numbered collection of
Questions (`v1`, `v2`, …). It holds no answers itself — those live on each
Question. Think of it as the exam's **cover sheet**: "Exam v1, 50 questions,
frozen on Nov 25, here's what changed since v0".

```
GoldSet v1 (frozen)               GoldSet v2 (draft)
 ├── python-creator                ├── python-creator    (same)
 ├── asyncio-docs                  ├── asyncio-docs      (typo fixed)
 └── ... 48 more                   ├── ... 48 more
                                   └── rust-creator      (new)
```

## 2. Why it exists

Drift detection compares two runs and says "the score moved". That only means
something if both runs asked **exactly the same questions with exactly the same
answers**. Otherwise the change could be *us* changing the test, not the vendor.

The GoldSet gives us two guarantees:

1. **A fixed boundary** — "these 50 questions, no more, no less".
2. **Immutability** — once frozen, nothing in it changes, ever.

So every Run points at one frozen GoldSet, and two runs on the same GoldSet are
comparable. Improvements (fixes, new questions) go into a new version, and old
scores stay valid because their GoldSet never changed underneath them.

## 3. How it fits the core loop

```
write goldsets/v1.yaml ──► load into DB (draft) ──► reload as often as needed
                                                           │
                                               POST /gold-sets/{id}/freeze
                                                           ▼
                                                  GoldSet v1 (frozen)
                                                           │
                                     Run (gold_set_id = v1) ──► Trials ──► Scores
                                                           │
                                     Baseline = a Run on v1 ──► DriftReports on v1
```

- **Authoring:** draft GoldSets are edited freely (through the YAML file).
- **Freezing:** one-way switch; validates, then locks.
- **Running:** a Run can only use a **frozen** GoldSet (decision 2 below).
- **Drift:** a baseline and the runs compared to it must share the same GoldSet.

## 4. State machine

```
            freeze (validated)
  draft  ──────────────────────►  frozen
    │                              (forever; no way back)
    └── delete (only if draft)
```

| Status | Questions | Can be used by a Run? | Can be deleted? |
|---|---|---|---|
| `draft` | add / edit / delete (via YAML reload) | ❌ | ✅ |
| `frozen` | read only — nothing changes, not even `verification` | ✅ | ❌ (runs point at it) |

There is no `retired` status. Old versions simply stay frozen. "Which version
is current?" = the frozen GoldSet with the highest `version`; it's derived,
not stored, so it can't get out of sync.

**Why no "unfreeze"?** If you could unfreeze, edit and refreeze, every Run
scored on that GoldSet would silently be pointing at different data. One-way
freezing makes "frozen" mean something you can trust without checking history.

## 5. Fields

| Field | Type | Null? | Why it exists |
|---|---|---|---|
| `id` | UUID | no | Primary key. Runs and Questions point at it. |
| `version` | INTEGER, UNIQUE, > 0 | no | The version number (shown as `v1`, `v2`). An integer, not text, so "latest" is just `MAX(version)` and ordering is never ambiguous (text would sort `v10` before `v2`). |
| `description` | TEXT | no | What this version is and what changed since the previous one, e.g. "v2: fixed typo in asyncio-docs, added 10 questions". A human changelog. |
| `status` | TEXT, CHECK in (`draft`, `frozen`) | no | The state machine above. Default `draft`. |
| `frozen_at` | TIMESTAMPTZ | yes | When it was frozen. Empty while draft. Needed for provenance, and for the authoring rule "answer settled ≥ 1 year *before the freeze*". |
| `content_hash` | TEXT | yes | A SHA-256 fingerprint of all its questions, computed at freeze (see §6). Empty while draft. Proves the content hasn't changed since freezing, and goes into Run provenance. |
| `created_at` | TIMESTAMPTZ, default now() | no | Audit field. |

**Constraints**

- `UNIQUE (version)` — one v1, one v2.
- `CHECK ((status = 'frozen') = (frozen_at IS NOT NULL))` — frozen ⇔ has a freeze time.
- `CHECK ((status = 'frozen') = (content_hash IS NOT NULL))` — frozen ⇔ has a fingerprint.
- `runs.gold_set_id` → `gold_sets.id` with `ON DELETE RESTRICT` — Postgres
  itself refuses to delete a GoldSet any Run points at. (`questions.gold_set_id`
  uses `ON DELETE CASCADE`: deleting a draft deletes its questions.)

## 6. The content hash (fingerprint)

At freeze time we compute:

```
content_hash = sha256( canonical JSON of all questions, sorted by key,
                       each with: key, text, scoring_unit, gold, verification )
```

- **Sorted by key, canonical JSON** (sorted object keys, no extra spaces) →
  the same content always gives the same hash.
- **Excludes `id` and `created_at`** → those differ between your laptop and the
  deployed server even when the questions are identical. Excluding them means
  "same hash = same exam" anywhere.

What it buys us:

1. **Tamper check.** Until we add a database trigger, someone (you, at 2am, in
   `psql`) could still `UPDATE` a frozen question. Recomputing the hash and
   comparing reveals it. A test can check this on every run.
2. **Provenance.** A Run records the hash, so a published score says *exactly*
   which exam produced it.
3. **Cheap comparison.** Two GoldSets with the same hash have identical content.

## 7. Freezing: what happens, step by step

`POST /gold-sets/{id}/freeze` runs in **one database transaction**:

1. `SELECT … FROM gold_sets WHERE id = :id FOR UPDATE` — lock the GoldSet row.
2. Check `status = 'draft'` (else `409 Conflict: already frozen`).
3. Validate:
   - at least one question (week 1 target: 50);
   - no two questions with the same `text` (they'd share a cassette and
     double-count one question in every average).
   - (Gold shape is already validated when questions are loaded.)
4. Compute `content_hash`.
5. `UPDATE gold_sets SET status = 'frozen', frozen_at = now(), content_hash = …`.
6. Commit.

**Why the lock in step 1?** Imagine the YAML loader is adding questions at
the same moment you freeze. Without the lock: freeze validates and hashes 50
questions, the loader commits a 51st, freeze commits. Now the GoldSet is
"frozen" with 51 questions and a hash of 50. The loader takes the same row
lock and checks `status = 'draft'` before writing, so the two operations
happen one after the other, never interleaved. (This is a small preview of
week 2: transactions and `SELECT … FOR UPDATE`.)

## 8. Authoring workflow (the YAML file is the source)

Each version is one file in the repo:

```yaml
# goldsets/v1.yaml
version: 1
description: First 50 questions.
questions:
  - key: python-creator
    text: Who created the Python programming language?
    scoring_unit: entities
    gold:
      - name: Guido van Rossum
        aliases: [Guido van Rossum, van Rossum]
    verification: https://docs.python.org/3/faq/general.html — FAQ names him as creator
  # ...
```

Loading it does a **sync**, not just an insert: the database must end up
matching the file exactly.

1. Create the GoldSet `v1` if it doesn't exist (draft).
2. Upsert every question by `key` (§10 of Question.md).
3. **Delete** draft questions whose key is no longer in the file.

Step 3 matters: if you delete a question from the YAML and only upserted,
the old row would stay in the database forever, and the GoldSet would contain
a question you thought you removed.

Making v2: copy `v1.yaml` to `v2.yaml`, change `version: 2`, edit, load,
freeze. No special "copy" feature needed — git shows the diff between versions.

## 9. API

| Method & path | What it does | Notes |
|---|---|---|
| `POST /gold-sets` | Create a draft `{version, description}` | `409` if version exists |
| `GET /gold-sets` | List all versions | |
| `GET /gold-sets/{id}` | One GoldSet + question count | |
| `PUT /gold-sets/{id}/questions` | Replace the whole question list (the sync in §8) | Draft only, else `409` |
| `POST /gold-sets/{id}/freeze` | Validate and freeze (§7) | `409` if already frozen, `422` if validation fails |
| `DELETE /gold-sets/{id}` | Delete a draft and its questions | Draft only, else `409` |

Two REST design choices worth noticing (week 1 fundamentals):

- **`PUT` for the question list.** `PUT` means "make the resource exactly this".
  Sending the same file twice gives the same result → it's **idempotent**, which
  is exactly what a sync is.
- **Freeze is its own action (`POST …/freeze`), not `PATCH {status: "frozen"}`.**
  Freezing isn't editing a field: it validates, computes a hash and is
  irreversible. A generic `PATCH status` would also invite `PATCH {status:
  "draft"}` — the unfreeze we forbid.

## 10. Decisions to review

1. **Runs only on frozen GoldSets.** Simplest rule: every score is tied to
   content that can never change. Cost: to try draft questions against real
   vendors you must freeze a version first — so early on you may make a few
   throwaway versions (v1, v2, v3…). Versions are cheap; that's fine.
2. **Strict freeze, no exceptions** — even a `verification` typo needs a new
   version. One simple rule is easier to enforce and trust.
3. **One family of versions** (`v1`, `v2`, …), no names like "tech-set". We
   only have one exam. Add a `name` column later if a second exam ever appears.
4. **`content_hash`** — included because it's cheap and turns "frozen" from a
   promise into something checkable.

## 11. Subtleties

- **Comparing across versions.** A Run on v1 and a Run on v2 are *not* directly
  comparable, even if only one question changed. When a new version becomes
  current, it needs **a new baseline** run. Unchanged questions (same `key`,
  same `text`) hit the same cassettes, so re-recording costs credits only for
  questions that changed.
- **Version numbers aren't reused.** If you delete draft v3 and create a new
  one, it can be v3 again only because v3 never got frozen (nothing ever
  pointed at it). A frozen version number is taken forever.
- **The YAML can drift from the DB after freezing.** Someone edits `v1.yaml`
  after v1 is frozen; the loader rejects it (`409`). The database is the
  record of what was frozen; the hash proves it.

## 12. Not in this version

| Idea | Why not now |
|---|---|
| `retired` status | Old versions just stay frozen; "current" is derived. |
| `name` (several exams) | Only one exam. |
| `parent_id` (v2 came from v1) | The description + git history say it. Add if we need automatic diffs. |
| DB trigger blocking writes to frozen questions | Week 2+, as a "defence in depth" exercise; the hash catches tampering meanwhile. |
| Runs on drafts | See decision 1. |
