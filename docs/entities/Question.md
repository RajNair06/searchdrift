# Question

> Status: **locked (2026-11-22)**. Built in week 1 (table + 50 questions),
> scoring logic in week 2.

## 1. What it is

A **Question** is one item on the exam we give to search vendors. It holds:

- what we ask (the question `text`, sent unchanged to vendors in Tier 1 and
  given to the agent in Tier 2),
- what the right answer is (the **gold answer**),
- how to grade a vendor's results against that answer (the **scoring unit**),

Every question belongs to exactly one **GoldSet** (e.g. `v1`).

## 2. Why it exists

SearchDrift's output is "vendor X scored 0.71". A score only means something if
we know **what was asked** and **what the correct answer was**. The Question is
that ground truth. Everything else (Trial, Score, DriftReport) points back to it.

Without a fixed question + fixed answer, a score change could mean "the vendor
changed" *or* "we changed the test". Questions (inside a frozen GoldSet) remove
the second possibility.

## 3. How it fits the core loop

```
author questions ──► GoldSet frozen ──► Run created
                                           │
                     for each Question × Vendor × repeat
                                           ▼
                     Trial: send question.text to vendor as-is (Tier 1)
                            or give question.text to the agent (Tier 2)
                                           ▼
                     Score: compare results to question.gold
                            using question.scoring_unit
```

- **Authoring** (week 1): you write questions in a file in the repo
  (`goldsets/v1.yaml`) and load them into the database. The file is the
  source you edit and review in git; the table is what runs use.
- **Freezing**: when the GoldSet is frozen, its questions can no longer be
  added, edited or deleted.
- **Running**: a Run creates one Trial per (question × vendor × repeat).
- **Scoring**: the scorer reads `gold` + `scoring_unit` to grade each Trial.

## 4. Only stable questions (v1)

Every question in v1 is **stable**: its answer has been on the web for at
least a year (or is timeless), and it will never change.

Why: drift detection needs questions whose scores **should stay flat**. If a
score moves, the cause should be the vendor, not the world.

| Question type | Allowed? | Why |
|---|---|---|
| **Settled fact**: "Who created the Python programming language?" | ✅ | Every serious vendor has indexed it for years. A score change means the vendor changed. |
| **Moving answer**: "Who is the *current* CEO of X?" | ❌ | The real answer can change at any time. Our frozen gold answer silently goes wrong, and the vendor is marked down for being *correct*. |
| **Recent event**: "Who won the 2026 Nobel Prize in Physics?" (asked in Nov 2026) | ❌ | Vendors are still crawling it, so scores rise as their indexes catch up. That rise would look like drift but isn't. |

### Decision: freshness is out of the MVP (2026-11-22)

The original plan split questions into *stable* (drift) and *fresh*
(freshness). We dropped fresh questions for v1:

- Fresh scores are *expected* to move, so they must never feed the drift alarm.
  That needs a label on every question (`kind`) plus an `event_date`, and a
  separate freshness report: a second feature to build.
- Drift is the core of the project; stable-only questions keep it clean.

**Cost:** no freshness measurement ("which vendor surfaces news fastest?").
**Adding it later:** a new GoldSet version adds a nullable `event_date`
(present = fresh question), recent-event questions, and a separate freshness
report. Fresh questions are excluded from drift detection. The gap rule we
worked out then applies: stable = answer ≥ 1 year old; fresh = ≤ 90 days before
the GoldSet freeze; anything in between is not written, because its score
behaviour is unpredictable.

## 5. Scoring units: how a question is graded

Different questions have different kinds of "right answer", so each question
declares its **scoring unit**:

| Scoring unit | Use when the right answer is… | Example | Gold answer is a list of… |
|---|---|---|---|
| `entities` | some named things (people, companies, versions, places) | "Who created Python?" | entities, each with aliases |
| `urls` | specific pages | "Where are the official docs for Python's asyncio module?" | URLs (exact or prefix match) |

### How Tier 1 scoring works (one rule for both units)

A vendor returns its **top k results** (k is the same for every vendor, set
on the Run, e.g. k = 5). Each result has a URL, a title and some text.

- A **gold item** is one entity or one URL in the gold answer.
- A result is **relevant** if it matches at least one gold item:
  - `urls`: the result's URL matches a gold URL (after canonicalisation).
  - `entities`: the result's title/text mentions a gold entity (any alias).

Then:

```
precision = relevant results returned / results returned
recall    = gold items found in any result / total gold items
F1        = 2 · P · R / (P + R)        (0 if P + R = 0)
```

In words: **precision** = "how much of what you returned was useful?";
**recall** = "how much of the right answer did you find?".

Example — "Who are the authors of *Attention Is All You Need*?" (8 gold
entities). The vendor returns 5 results; 4 of them mention at least one author,
and together they mention 6 of the 8 authors:
precision = 4/5 = 0.80, recall = 6/8 = 0.75, F1 ≈ 0.77.

> **Why this definition?** For entity questions, "precision" in the textbook
> sense needs to know every entity the vendor returned, which means extracting
> entities from free text (unreliable, or needs an LLM). Measuring precision
> **per result** stays fully deterministic, and gives URL and entity
> questions the same meaning, so their scores can be averaged together.

### Canonicalisation (making "the same thing" compare equal)

Raw strings rarely match exactly, so both the gold answer and the vendor
results are normalised the same way before comparing:

- **Entities:** Unicode normalise (NFKC), lowercase, collapse whitespace, strip
  punctuation, then match **whole words only** (so "Go" doesn't match "good").
  Each entity lists its aliases ("Guido van Rossum", "van Rossum").
- **URLs:** lowercase the host, drop `http(s)://` and `www.`, drop the
  `#fragment`, drop tracking parameters (`utm_*`), drop the trailing `/`.
  A gold URL with `match: prefix` matches any page under that path.

The gold answer is stored **as written**, not pre-normalised. The normalising
code is part of the scorer, and the scorer can be improved later without
rewriting the gold set. (A changed scorer can change scores, so the scorer
version goes into Run provenance.)

## 6. Fields

| Field | Type | Null? | Why it exists |
|---|---|---|---|
| `id` | UUID | no | Primary key. A surrogate key (meaningless ID) so other tables (Trial) can point at a question with a small, never-changing value. |
| `gold_set_id` | UUID, FK → gold_sets.id | no | Which GoldSet this question belongs to. Freezing works at the GoldSet level. |
| `key` | TEXT | no | A human-readable ID you choose, e.g. `python-creator`. Unique within a GoldSet. Lets you find a question in logs and in the YAML file, and match "the same question" across GoldSet versions (`v1` → `v2`). |
| `text` | TEXT | no | The question in natural language, e.g. "Who created the Python programming language?". Used three ways: sent **unchanged** to every vendor in Tier 1, given to the agent in Tier 2 (which writes its own queries), and read by humans in reports. It must stay byte-identical across runs (same text → same cassette key → fair comparison). |
| `scoring_unit` | TEXT, CHECK in (`entities`, `urls`) | no | Tells the scorer which matching rule to use and what shape `gold` has. |
| `gold` | JSONB | no | The gold answer: a non-empty list of gold items. Shape depends on `scoring_unit` (see §7). |
| `verification` | TEXT | no | How you know the gold answer is correct (a source URL + a short note). Required on purpose: an unverified gold answer makes every score built on it worthless. |
| `created_at` | TIMESTAMPTZ, default now() | no | When the row was created. Standard audit field. |

**Constraints**

- `UNIQUE (gold_set_id, key)` — no two questions with the same key in one GoldSet.
  This also gives us an index starting with `gold_set_id`, so "all questions
  of GoldSet v1" is fast without a separate index (a week 2 indexing lesson).
- Enums are `TEXT + CHECK`, not native Postgres enums: adding a value later is
  a one-line constraint change instead of an `ALTER TYPE` migration.
- `gold` shape is validated in Python (a Pydantic model) when questions are
  loaded, not in SQL. The database checks only that it is valid JSON.

## 7. The `gold` field: shapes and examples

`scoring_unit = entities`:

```json
[
  {"name": "Guido van Rossum", "aliases": ["Guido van Rossum", "van Rossum"]}
]
```

`scoring_unit = urls`:

```json
[
  {"url": "https://docs.python.org/3/library/asyncio.html", "match": "prefix"}
]
```

How two questions look in the authoring file (`goldsets/v1.yaml`):

```yaml
- key: python-creator
  text: Who created the Python programming language?
  scoring_unit: entities
  gold:
    - name: Guido van Rossum
      aliases: [Guido van Rossum, van Rossum]
  verification: https://docs.python.org/3/faq/general.html — FAQ names him as creator

- key: asyncio-docs
  text: Where is the official documentation for Python's asyncio module?
  scoring_unit: urls
  gold:
    - url: https://docs.python.org/3/library/asyncio.html
      match: prefix
  verification: official Python docs site
```

### Why `gold` is JSONB inside Question, not its own table

| Option | Pros | Cons |
|---|---|---|
| **JSONB column on Question** ✅ | One row = whole question. Always read together. Simple to load from YAML. | Can't easily query "all questions mentioning entity X" (we don't need to). |
| Separate `gold_items` table | Normalised; queryable per item; per-item history. | Extra table and joins for something that is frozen and always read as a whole. |

We'll split it out only if a real need appears (e.g. human re-labelling of
individual gold items for the LLM judge in week 6).

## 8. Rules for writing good questions (authoring guide)

1. **One clear, checkable answer.** If two careful people could disagree, rewrite it.
2. **Settled answers only.** The answer must have been on the web for at least a
   year, or be timeless. No "current", "latest", "now", and no recent events.
3. **Avoid ambiguous short entities.** "Go", "Swift", "Apple" match too much text;
   use a longer alias ("Go programming language") or a `urls` question.
4. **The gold list is complete for entity questions.** If the question asks for
   "the authors", list *all* of them, or recall is meaningless.
5. **Always fill in `verification`.**
6. **Mix difficulty.** Some questions every vendor gets right; some that are hard
   (niche, technical, obscure). Questions everyone aces or everyone fails can't
   show drift.

## 9. State and lifecycle

A Question has no state machine of its own. Its lifecycle follows its GoldSet:

| GoldSet status | What you can do to its questions |
|---|---|
| `draft` | add, edit, delete |
| `frozen` | nothing — read only |

In week 1 this rule lives in application code (the API checks the GoldSet's
status before any write). Later we can add a database trigger so even a
manual SQL update can't change a frozen question — a good "defence in depth"
lesson.

Corrections after freezing (e.g. you find a wrong gold answer) go into a **new
GoldSet version**, never into the frozen one. Otherwise old scores would
silently stop matching the data they were computed from.

## 10. API

Questions are managed through their GoldSet (designed in the GoldSet doc):

- `PUT /gold-sets/{id}/questions` — replace the whole question list from the
  YAML (draft only): upsert by `key`, delete keys no longer in the file
- `GET /gold-sets/{id}/questions` — list
- `GET /questions/{id}` — one question

## 11. Subtleties

- **Unequal text lengths across vendors.** One vendor returns a 2,000-character
  page extract, another a 150-character snippet. The longer text has more
  chances to mention an entity, so entity matching favours verbose vendors.
  Likely fix: cut each result's text to the same length before matching.
  → decide in the **Score** doc (week 2).
- **Zero results.** If a vendor returns nothing, precision is technically
  undefined (0/0). We score it as precision = 0, recall = 0: returning nothing
  is a failure, not "no opinion".
- **Duplicate results.** If the same URL appears twice in the top k, count it once.
- **The text is a frozen instrument.** Fixing a typo in `text` changes the
  query vendors receive, so it changes what we measure. That needs a new
  GoldSet version, not an edit.
- **Gold incompleteness for `urls`.** There may be good pages you didn't list
  as gold; a vendor returning them gets lower precision unfairly. `match: prefix`
  helps; keep `urls` questions to cases where the "right page" is clear-cut.

## 12. Not in this version (and when they might come)

| Idea | Why not now |
|---|---|
| `category` (technical, general, …) | **Considered and rejected (2026-11-22).** Grading depends on the answer's shape (`scoring_unit`), not the topic, and recency is handled by allowing only settled answers (§4). Cost: no per-topic leaderboard breakdown. Cheap to add later in a new GoldSet version if that breakdown is wanted. |
| `difficulty` tag | Same reasoning; revisit only if we need to check the gold set's difficulty mix. |
| Separate `query` field | **Rejected (2026-11-22).** A hand-written keyword query picks a query style, and vendors handle styles differently (Serper/Google likes keywords; Exa and Tavily are built for natural language), so it would quietly favour some vendors. Sending the natural-language `text` is fairer and closer to how agents and RAG apps really call these APIs. |
| Ambiguous questions | Break rule 1 (one checkable answer) and add noise to the drift signal. Maybe later, with the LLM judge or Tier 2. |
| Per-question `k` | k is a Run setting so all questions are measured the same way. |
| Separate gold-items table | See §7. |
| `kind` + `event_date` (fresh questions) | **Deferred (2026-11-22).** See §4. Comes back with the freshness feature, after the MVP. |
| Moving-answer questions | Never as-is: the gold answer would go stale. Would need periodic re-verification. |
