# Vendor

> Status: **locked (2026-11-22)**. Built in week 1 (table + 3 adapters);
> rate-limit field arrives in week 2.

## 1. What it is

A **Vendor** is one search API we benchmark: `tavily`, `exa`, `serper`.

There are two halves, and keeping them apart is the main idea of this doc:

| Half | Where it lives | What it holds |
|---|---|---|
| **Vendor row** (data) | `vendors` table in Postgres | Identity, on/off switch, our credit budget |
| **Vendor adapter** (code) | `searchdrift/vendors/tavily.py`, … | How to build the HTTP request and how to read the response |

The row says **"may we call Tavily, and how much?"**. The adapter says
**"how do we talk to Tavily?"**.

## 2. Why it exists

- **Identity.** Trials, cassettes, ledger entries and drift reports all need to
  say *which* vendor. A table gives them something to point at (a foreign key),
  so a typo like `tavilly` is rejected by the database instead of becoming a
  silent fourth vendor.
- **Budget (the cost constraint).** Free credits are scarce. The credit ledger
  must check "is there budget left?" before every live call. The budget lives
  on the vendor row, and in week 2 that row becomes the thing we **lock** so
  that 50 workers can't all see "1 credit left" and all spend it at once.
- **Kill switch.** If a vendor starts returning garbage or burning credits
  unexpectedly, you flip `enabled = false` and live calls stop immediately —
  no redeploy.

### Why a table and not just a Python config dict?

| | Python config only | Table ✅ |
|---|---|---|
| Foreign keys from trials/ledger | ❌ nothing to point at | ✅ |
| Change budget / kill switch without redeploy | ❌ | ✅ |
| Lock it inside the ledger's transaction (week 2) | ❌ | ✅ |
| Adding a new vendor | edit code | edit code **and** add a row |

Adding a vendor always needs code (a new adapter) anyway, so the extra row
costs almost nothing.

## 3. How it fits the core loop

```
Trial (question × vendor × repeat)
   │
   ▼
adapter.build_request(question.text, k)      ← pure: no network, no secrets
   │
   ▼
cassette key = hash(request)  ── hit? ──► recorded response (free)
   │ miss
   ▼
vendor.enabled?  budget left? (ledger)       ← the vendor ROW is checked here
   │ yes
   ▼
send over HTTP (httpx), record cassette, record ledger entry
   │
   ▼
adapter.parse_response(body) → list[SearchResult]   ← pure again
   │
   ▼
Score
```

**The key design decision: adapters never touch the network.** They only
*translate*: question → HTTP request, HTTP response → results. Sending is done
by one shared gate that runs cassette → kill switch → ledger → send → record.

Why: if each adapter called `httpx` itself, every adapter would have to
remember to check the cassette and the ledger. One forgetful adapter = credits
spent with no record. With a single gate, **it is impossible** for an adapter
to bypass the budget, because adapters have no way to send anything.

## 4. Fields

| Field | Type | Null? | Why it exists |
|---|---|---|---|
| `id` | TEXT, PK, e.g. `tavily` | no | A short, readable, permanent name. Used as a **natural key** (see below). Matches the adapter's name in code. |
| `enabled` | BOOLEAN, default `true` | no | Kill switch. `false` → no live calls (replay from cassettes still works, since that's free). |
| `budget_calls` | INTEGER, ≥ 0 | no | **Our own** cap on live calls in one budget period. Set well below the vendor's free tier (see §6). |
| `budget_period` | TEXT, CHECK in (`monthly`, `total`) | no | Tavily's credits refresh monthly; Exa's and Serper's are one-time grants, so the cap is lifetime (`total`). |
| `created_at` | TIMESTAMPTZ, default now() | no | Audit field. |
| `rate_limit_per_min` | INTEGER | — | **Week 2**, with the Redis rate limiter. |

### Natural key vs surrogate key (a deliberate difference from Question/GoldSet)

Question and GoldSet use UUIDs (surrogate keys). Vendor uses `'tavily'`
(a natural key). Why the difference?

- A vendor's name is **global, short and never changes**. A question's `key`
  is only unique *within* a GoldSet and could be reused across versions.
- `vendor_id = 'tavily'` in a trial or ledger row is readable in `psql`
  without a join. That's handy when debugging spend at 2am.
- Risk of natural keys: if the "never changes" assumption breaks, renaming
  touches every referencing row. For a vendor slug, that's very unlikely.

### What is deliberately NOT stored

| Not stored | Where it lives instead | Why |
|---|---|---|
| **API key** | `.env` → environment variable (`TAVILY_API_KEY`) | Secrets never go in the database: DB dumps, backups and logs leak. |
| **Spent so far** | Computed from ledger entries | Storing it too would mean two records of the same fact that can disagree. One source of truth: the ledger. (Week 2 may add a cached counter for speed — a lesson in when to break this rule.) |
| Base URL, request options | Adapter code | They're part of *how to talk*, and they end up in the cassette key anyway. |
| Display name ("Tavily") | Code / leaderboard | Not needed by any query. |
| Cost per call | — | v1 counts budget in **calls**: each search we make costs one credit on every vendor (we use the basic search modes). Add `credits_per_call` if we ever use a mode that costs more. |

## 5. The adapter interface (code)

Every vendor adapter implements the same small interface, so the rest of the
system never knows which vendor it's talking to (the **adapter pattern** — an
LLD pattern you'll name in week 7 interviews).

```python
class SearchResult(BaseModel):
    rank: int          # 1 = top result
    url: str
    title: str
    text: str          # snippet / extract, whatever the vendor returns

class HttpRequest(BaseModel):
    method: str
    url: str
    headers: dict[str, str]   # WITHOUT the API key (added by the gate at send time)
    body: dict

class VendorAdapter(Protocol):
    vendor_id: str                                   # "tavily"
    def build_request(self, query: str, k: int) -> HttpRequest: ...
    def parse_response(self, body: dict) -> list[SearchResult]: ...
```

Both methods are **pure functions**: same input → same output, no network, no
clock, no randomness. That makes them trivially testable (feed a recorded JSON
body to `parse_response`, check the results) and makes the cassette key
stable.

### Why the three vendors need adapters at all

Each returns "a list of results", but every vendor names things differently.
Roughly (to be verified against each vendor's docs when we build):

| | Tavily | Exa | Serper |
|---|---|---|---|
| Endpoint | `POST api.tavily.com/search` | `POST api.exa.ai/search` | `POST google.serper.dev/search` |
| Query field | `query` | `query` | `q` |
| Result count | `max_results` | `numResults` | `num` |
| Results list | `results[]` | `results[]` | `organic[]` |
| URL field | `url` | `url` | `link` |
| Text field | `content` | `text` (only if contents are requested) | `snippet` |

The adapter's whole job is mapping each column into one `SearchResult`.

## 6. Budgets: setting the numbers

Our budget is **our** safety cap, not the vendor's limit. It should be lower,
so we never hit the vendor's wall mid-run.

| Vendor | Free tier | Period | Suggested `budget_calls` | Reasoning |
|---|---|---|---|---|
| `tavily` | 1,000 / month | `monthly` | 600 | Leaves room for manual testing and reset-date mismatch. |
| `exa` | 2,500 one-time | `total` | 2,000 | One-time: once gone, gone. Keep a reserve. |
| `serper` | 2,500 one-time | `total` | 2,000 | Same. |

A rough sense of scale: one Tier-1 run of 150 questions × 3 repeats = **450
calls per vendor**, minus cassette hits. Exa's 2,000 covers about four full
live runs, ever. That's why replay is the default and why a nightly live run
(week 7) must be sized carefully — a power-analysis question for week 5.

## 7. API

Vendors are created by a **seed migration**, not through the API: adding a
vendor needs a new adapter (code), so a "create vendor" endpoint would make
rows that can't do anything.

| Method & path | What it does |
|---|---|
| `GET /vendors` | List vendors with enabled flag, budget, and spent-this-period (computed from the ledger) |
| `PATCH /vendors/{id}` | Change `enabled` or `budget_calls` |

`PATCH` is right here (unlike GoldSet freezing) because these really are
plain field edits, reversible, with no side effects.

## 8. Subtleties

- **API key placement and the cassette key.** The cassette key is a hash of
  the request. If the API key were inside the hashed request, rotating your key
  would change every hash and make the whole cassette library useless — and
  the key would be saved in cassettes on disk. So `build_request` never
  includes the key; the gate adds it just before sending. (Some vendors accept
  the key in the JSON body; we always use the header form.)
- **Comparable requests.** Fairness depends on asking each vendor for the
  same thing: same `k`, and *some* text per result. Exa returns no text unless
  asked, so its adapter must request contents, or every entity question scores
  0 on Exa — an adapter bug that looks like a vendor failure. Check whether
  requesting text costs extra credits.
- **Adapter settings are part of the instrument.** Changing an adapter (say,
  Tavily `search_depth` basic → advanced) changes what we measure *and* the
  cassette keys. That's an instrument change, not vendor drift; the adapter
  settings are recorded in the Run's `config`.
- **Monthly reset dates.** Tavily's credits reset on your billing date, not
  the 1st. Our `monthly` period uses calendar months; the margin in §6 covers
  the mismatch.
- **Disabled ≠ deleted.** Never delete a vendor row: past trials and ledger
  entries point at it. Disable it instead.

## 9. Not in this version

| Idea | When |
|---|---|
| `rate_limit_per_min` | Week 2 (Redis rate limiter) |
| `credits_per_call` | Only if we use a vendor mode costing more than 1 credit |
| Firecrawl, SerpApi | After the MVP |
| Mock vendor | It's an adapter, not a row with a budget. Used in automated tests and the week 3 chaos test; never touches the ledger. |
