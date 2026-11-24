# Cassette

> Status: **locked (2026-11-22)**. Built in week 1 (vendor calls);
> LLM calls get cassettes in week 4.

## 1. What it is

A **Cassette** is **one recorded vendor call**: the exact request we sent, the
exact response we got back, how long it took, and when. The name comes from
tape recorders: record once, play back as often as you like.

```
Cassette
  request:   POST api.tavily.com/search  {"query": "Who created Python…", "max_results": 5, …}
  response:  200  {"results": [{"url": "https://docs.python.org/…", …}, …]}
  latency:   412 ms
  recorded:  2026-11-24 21:03:11 UTC
```

## 2. Why it exists

1. **Cost.** A live call spends a scarce credit. Replaying a cassette is free.
   Development, tests and CI run entirely on cassettes: zero credits, zero network.
2. **Evidence.** Every score must be traceable to *what the vendor actually
   said*. The cassette is that raw evidence; a Trial points at it.
3. **Reproducibility.** Replay gives byte-identical input every time, so a test
   that passes today passes tomorrow, and re-scoring an old run gives the same
   numbers unless the scorer changed.

## 3. How it fits the core loop

```
adapter.build_request(question.text, k)
        │
        ▼
request_hash = sha256(canonical request)
        │
   ┌────┴──────────────────────────────┐
   │ mode = replay                     │ mode = live
   ▼                                   ▼
find the cassette the source run       ledger check → add API key → send (httpx)
used for this trial (§6)                    │
   │ found?    │ not found                  ▼
   ▼           ▼                       INSERT new cassette (always a new row)
 use it    trial failed:                    │
           replay_miss                      ▼
   └──────────────┬─────────────────── trial.cassette_id = that cassette
                  ▼
        adapter.parse_response(cassette.response_body)
```

## 4. The request hash (the cassette key)

The hash is a fingerprint of the request: same request → same hash.

```
request_hash = sha256( "v1|" + canonical_json({
    "method": "POST",
    "url":    "https://api.tavily.com/search",
    "body":   {"max_results": 5, "query": "Who created Python…", "search_depth": "basic"}
}))
```

| Rule | Why |
|---|---|
| **In:** method, URL, body | These decide what the vendor returns. |
| **Out:** the API key | Rotating your key would change every hash and orphan the whole library. And the key would be saved on disk. The gate adds it after hashing (Vendor.md §8). |
| **Out:** timestamps, request IDs, anything random | They'd make every hash unique → nothing ever replays. |
| **Canonical JSON** (sorted keys, no whitespace) | `{"a":1,"b":2}` and `{"b":2,"a":1}` are the same request and must hash the same. |
| **`"v1\|"` prefix** | If we ever change *how* we hash, old and new hashes can't silently collide; we bump to `v2\|`. |

What changes the hash, and therefore means "a different request":
question `text`, `k`, adapter options (e.g. Tavily `search_depth`). That's
exactly the list of things that change *what we measure* — by design.

## 5. The surprise: one hash, many cassettes

The obvious design is a table `request_hash → response`, one row per hash.
**That doesn't work for us.** The same request is sent many times:

- 3 repeats in one live run → same hash, possibly 3 different responses;
- every nightly live run → same hash again, a new response each night.

All of those responses are evidence we need (repeats measure noise; nightly
runs measure drift). Overwriting would destroy them.

So: **a cassette is one recording, not one key.** `request_hash` is indexed
but **not unique**. Cassettes are **append-only**: inserted, never updated,
never deleted. A live call *always* inserts a new row.

## 6. Replay: which recording do you get?

If one hash has 40 recordings, replay must pick one — deterministically.

**Rule: a replay run names a source run, and each trial replays exactly what
the matching source trial got.**

```
Replay run R (config.replay_from_run_id = X)
  trial: tavily × "Who created Python…" × repeat 2
     → find X's trial with the same vendor, same request_hash, same repeat_index
     → use that trial's cassette
     → none? → failed, error_kind = replay_miss
```

Why this rule:

- **Deterministic.** The same replay always gets the same responses.
- **Repeats keep their variety.** Repeat 2 replays the original repeat 2, so
  the noise in the original data is reproduced, not flattened to zero.
- **Re-grading works across GoldSet versions.** v2 fixed a `gold` typo but kept
  the `text` → same hash → v2's replay finds v1-run responses → re-scored for
  free. (If `text` changed, the hash changed → `replay_miss`, correctly: we never
  asked the vendor that question.)
- **"Replay" always means "reproduce a specific past measurement"** — one clear
  meaning.

Alternative rejected: "use the latest recording for this hash". The answer
would change every time a new live run records, so tests and re-scores
wouldn't be stable.

This adds one setting to the Run's config: `replay_from_run_id` (required when
`mode = replay`).

## 7. Fields

| Field | Type | Null? | Why it exists |
|---|---|---|---|
| `id` | UUID | no | Primary key. Trials point at it. |
| `vendor_id` | TEXT, FK → vendors.id | no | Whose API this was. (Week 4 adds LLM cassettes; this becomes one of two namespaces.) |
| `request_hash` | TEXT | no | The key from §4. Indexed, not unique (§5). |
| `request` | JSONB | no | Method, URL, headers (**API key removed**), body. Lets you see exactly what was asked, and recompute the hash to check it. |
| `status_code` | INTEGER | no | HTTP status: 200, 429, 503… |
| `response_body` | TEXT | no | The raw response, exactly as received. |
| `latency_ms` | INTEGER | no | How long the vendor took. A property of the call, so it lives here (Trial.md §4). Feeds the latency numbers on the leaderboard. |
| `recorded_at` | TIMESTAMPTZ, default now() | no | When the call happened — the cassette's age. |

**Index:** `(request_hash)` for lookups. The replay rule in §6 goes through the
source run's trials, which are already indexed by `run_id`.

### Why `response_body` is TEXT, not JSONB

JSONB is Postgres's parsed JSON format: it **reorders keys, removes
duplicate keys and drops whitespace**. Usually fine — but this column is
evidence of "exactly what the vendor sent". TEXT keeps the exact bytes. It
also stores non-JSON responses (an HTML error page from a proxy) that JSONB
would reject. `parse_response` does `json.loads` itself.

## 8. What gets recorded

| Outcome | Recorded? | Trial ends as |
|---|---|---|
| 200 with results | ✅ | `succeeded` |
| 200 with 0 results | ✅ | `succeeded` (scored 0) |
| 4xx / 5xx response | ✅ — it *is* a response, and evidence of a vendor failure; tests can replay it to check error handling | `failed`, `http_error`, with `cassette_id` set |
| Timeout / connection error | ❌ — there's no response to record | `failed`, `timeout`, no cassette |

(Small fix to Trial.md: `cassette_id` is required for `succeeded`, and
*optional* for `failed` — set when a failure response was received.)

## 9. Cassettes in tests and CI

CI starts with an empty database, so cassettes must also exist as **files in
the repo**:

- **Adapter unit tests:** a recorded `response_body` saved as
  `tests/fixtures/tavily_python_creator.json`; feed it to `parse_response`,
  check the results. No database needed.
- **End-to-end tests:** an export command writes one recorded run (its GoldSet,
  trials and cassettes) to `tests/fixtures/runs/<name>.json`. The test loads
  it into the test database and creates a `replay` run from it.

That's the week 1 deliverable: record all 3 vendors live once, export it, and
the whole suite then passes with no network.

## 10. Subtleties

- **Secrets in recordings.** The API key is stripped from `request` before
  saving. A test should assert that no stored cassette contains a key, because
  fixture files get committed to git.
- **Size.** A response is roughly 5–50 KB. 450 per live run, one run a night
  → a few GB a year. Postgres compresses large TEXT values automatically
  (TOAST), so this is fine for the MVP; a retention policy can come later.
- **Cassettes don't expire.** Age is just a fact (`recorded_at`). Whether old
  data is acceptable is the *Run's* decision (live vs replay), not the
  cassette's.
- **A failed live call may still have cost a credit.** The vendor might charge
  for a 500, or for a request whose response timed out. That uncertainty is
  the ledger's problem → **LedgerEntry** doc.
- **Hash check.** Because `request` is stored, we can recompute every hash and
  confirm it matches `request_hash` — a cheap integrity test.

## 11. Decisions to review

1. **One cassette = one recording**; the hash is not unique; append-only.
2. **Replay = reproduce a source run**, trial by trial (`replay_from_run_id`).
3. **Raw TEXT response**, not JSONB.
4. **Record HTTP error responses**, not timeouts.
5. **Fixtures in the repo** for tests and CI.

## 12. Not in this version

| Idea | When |
|---|---|
| LLM cassettes (hash of model, messages, temperature, …) | Week 4 |
| Retention / archiving old cassettes | When size actually hurts |
| Compression beyond TOAST | Same |
