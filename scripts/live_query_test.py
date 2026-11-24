"""Live query test: query all 3 vendors with 2 gold questions.

Usage:
    uv run python scripts/live_query_test.py

What this does:
    1. Loads 2 gold questions from the database (1 entity, 1 URL)
    2. For each question, queries all 3 vendors (Tavily, Exa, Serper)
    3. Records each response as a cassette
    4. Prints results

Expected output:
    - 6 cassettes created (2 questions × 3 vendors)
    - Credits spent: 6
    - Proof that the pipeline works end-to-end

⚠️  WARNING: This script makes real API calls and spends credits.
    Only run when you want to verify the pipeline with live data.
"""

import asyncio
import json
import uuid

from sqlalchemy import select

from searchdrift.api.app import app, lifespan
from searchdrift.cassette import execute_trial
from searchdrift.client import VendorClient
from searchdrift.config import get_settings
from searchdrift.models import GoldSet, Question, Vendor
from searchdrift.vendors import get_adapter


# Which 2 questions to test (1 entity, 1 URL)
TEST_QUESTION_KEYS = ["python-creator", "github-official"]

# All 3 vendors
VENDOR_IDS = ["tavily", "exa", "serper"]


def get_api_key(vendor_id: str, settings) -> str:
    """Get the API key for a vendor from settings."""
    key_map = {
        "tavily": settings.tavily_api_key,
        "exa": settings.exa_api_key,
        "serper": settings.serper_api_key,
    }
    key = key_map.get(vendor_id)
    if key is None:
        raise ValueError(
            f"No API key for {vendor_id}. Set {vendor_id.upper()}_API_KEY in .env"
        )
    return key.get_secret_value()


async def run_live_queries():
    """Query all 3 vendors with 2 gold questions."""
    settings = get_settings()

    print("=" * 70)
    print("LIVE QUERY TEST")
    print("=" * 70)
    print(f"Questions: {TEST_QUESTION_KEYS}")
    print(f"Vendors: {VENDOR_IDS}")
    print(f"Expected cassettes: {len(TEST_QUESTION_KEYS) * len(VENDOR_IDS)}")
    print("⚠️  This will spend real credits. Press Ctrl+C to abort...")
    print()

    async with lifespan(app):
        async with app.state.sessionmaker() as session:
            # Load the gold questions
            result = await session.execute(
                select(Question).where(Question.key.in_(TEST_QUESTION_KEYS))
            )
            questions = {q.key: q for q in result.scalars().all()}

            if len(questions) != len(TEST_QUESTION_KEYS):
                missing = set(TEST_QUESTION_KEYS) - set(questions.keys())
                print(f"ERROR: Questions not found in DB: {missing}")
                print("Run scripts/seed_data.py first.")
                return

            # Verify vendors exist
            for vid in VENDOR_IDS:
                vendor = await session.get(Vendor, vid)
                if vendor is None:
                    print(f"ERROR: Vendor '{vid}' not in database.")
                    print("Run scripts/seed_data.py first.")
                    return

            print("Questions loaded:")
            for key, q in questions.items():
                print(f"  - {key}: {q.text}")
            print()

            # Query each vendor for each question
            cassettes_created = 0
            for question_key in TEST_QUESTION_KEYS:
                q = questions[question_key]
                print(f"{'='*70}")
                print(f"Question: {q.text}")
                print(f"Scoring unit: {q.scoring_unit}")
                print(f"Gold answer: {q.gold}")
                print(f"{'='*70}")

                for vendor_id in VENDOR_IDS:
                    print(f"\n  → Querying {vendor_id}...")
                    adapter = get_adapter(vendor_id)
                    api_key = get_api_key(vendor_id, settings)

                    async with VendorClient(adapter, api_key) as client:
                        result = await execute_trial(
                            db=session,
                            adapter=adapter,
                            question_text=q.text,
                            vendor_id=vendor_id,
                            repeat_index=1,
                            k=5,
                            client=client,
                            replay_from_run_id=None,  # Live mode
                        )

                    if result.error_kind:
                        print(f"    ❌ ERROR: {result.error_kind} - {result.error}")
                    else:
                        c = result.cassette
                        cassettes_created += 1
                        # Parse response to show a summary
                        try:
                            body = json.loads(c.response_body)
                            results = adapter.parse_response(body)
                            print(f"    ✅ Cassette created (id={c.id})")
                            print(f"       Status: {c.status_code}, "
                                  f"Latency: {c.latency_ms}ms, "
                                  f"Results: {len(results)}")
                            if results:
                                print(f"       Top result: {results[0].title}")
                                print(f"       URL: {results[0].url}")
                        except (json.JSONDecodeError, KeyError, ValueError) as e:
                            print(f"    ⚠️  Cassette created but response unparseable: {e}")
                            print(f"       Status: {c.status_code}, "
                                  f"Latency: {c.latency_ms}ms")

            # Commit all cassettes
            await session.commit()
            print(f"\n{'='*70}")
            print(f"SUMMARY")
            print(f"{'='*70}")
            print(f"Cassettes created: {cassettes_created}")
            print(f"Credits spent: {cassettes_created}")
            print("Done! Cassettes are now in the database.")


if __name__ == "__main__":
    asyncio.run(run_live_queries())
