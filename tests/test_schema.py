"""Tests that verify the database schema exists and enforces its constraints.

These tests use the real Postgres from compose.yaml (host port 15432). They
prove that:
1. All 7 tables were created by the migration.
2. Check constraints reject invalid data (e.g., negative budget, wrong status).
3. Foreign keys prevent orphaned rows (e.g., a trial pointing at a deleted vendor).
4. Unique constraints prevent duplicates (e.g., two questions with the same key in one GoldSet).
"""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from searchdrift.models import (
    GoldSet,
    Question,
    Run,
    Trial,
    Vendor,
)


async def test_all_tables_exist(db: AsyncSession):
    """Verify all 7 tables were created by the migration."""
    result = await db.execute(
        text("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_type = 'BASE TABLE'
              AND table_name NOT IN ('alembic_version')
            ORDER BY table_name
        """)
    )
    tables = sorted(row[0] for row in result)
    expected = [
        "cassettes",
        "gold_sets",
        "ledger_entries",
        "questions",
        "runs",
        "trials",
        "vendors",
    ]
    assert tables == expected


async def test_gold_set_positive_version(db: AsyncSession):
    """GoldSet version must be > 0 (enforced by CHECK constraint)."""
    gs = GoldSet(id=uuid.uuid4(), version=0, description="invalid")
    db.add(gs)
    with pytest.raises(IntegrityError, match="ck_gold_sets_version_positive"):
        await db.flush()


async def test_vendor_budget_non_negative(db: AsyncSession):
    """Vendor budget_calls must be >= 0 (enforced by CHECK constraint)."""
    v = Vendor(
        id="test-vendor",
        enabled=True,
        budget_calls=-1,
        budget_period="monthly",
    )
    db.add(v)
    with pytest.raises(IntegrityError, match="ck_vendors_budget_non_negative"):
        await db.flush()


async def test_vendor_budget_period_valid(db: AsyncSession):
    """Vendor budget_period must be 'monthly' or 'total' (enforced by CHECK)."""
    v = Vendor(
        id="test-vendor",
        enabled=True,
        budget_calls=100,
        budget_period="weekly",  # invalid
    )
    db.add(v)
    with pytest.raises(IntegrityError, match="ck_vendors_budget_period"):
        await db.flush()


async def test_question_unique_key_per_gold_set(db: AsyncSession):
    """Two questions in the same GoldSet can't have the same key."""
    gs = GoldSet(id=uuid.uuid4(), version=99999, description="test")
    db.add(gs)
    await db.flush()

    q1 = Question(
        id=uuid.uuid4(),
        gold_set_id=gs.id,
        key="same-key",
        text="First question",
        scoring_unit="entities",
        gold=[{"name": "Answer", "aliases": ["Answer"]}],
        verification="test",
    )
    q2 = Question(
        id=uuid.uuid4(),
        gold_set_id=gs.id,
        key="same-key",  # duplicate
        text="Second question",
        scoring_unit="entities",
        gold=[{"name": "Answer", "aliases": ["Answer"]}],
        verification="test",
    )
    db.add(q1)
    await db.flush()
    db.add(q2)
    with pytest.raises(IntegrityError, match="uq_questions_gold_set_key"):
        await db.flush()


async def test_trial_success_requires_cassette(db: AsyncSession):
    """A trial with status='succeeded' must have a cassette_id (CHECK constraint)."""
    gs = GoldSet(id=uuid.uuid4(), version=99999, description="test")
    db.add(gs)
    await db.flush()

    q = Question(
        id=uuid.uuid4(),
        gold_set_id=gs.id,
        key="q1",
        text="Test?",
        scoring_unit="entities",
        gold=[{"name": "A", "aliases": ["A"]}],
        verification="test",
    )
    db.add(q)
    await db.flush()

    v = Vendor(id="test-vendor", enabled=True, budget_calls=100, budget_period="monthly")
    db.add(v)
    await db.flush()

    r = Run(
        id=uuid.uuid4(),
        gold_set_id=gs.id,
        config={"medium": "none", "mode": "live", "vendors": ["test-vendor"], "k": 5, "repeats": 1},
        code_version="abc123",
        status="pending",
    )
    db.add(r)
    await db.flush()

    # Try to create a succeeded trial without a cassette
    t = Trial(
        id=uuid.uuid4(),
        run_id=r.id,
        question_id=q.id,
        vendor_id=v.id,
        repeat_index=1,
        status="succeeded",
        cassette_id=None,  # missing
    )
    db.add(t)
    with pytest.raises(IntegrityError, match="ck_trials_succeeded_has_cassette"):
        await db.flush()


async def test_foreign_key_prevents_orphaned_trial(db: AsyncSession):
    """A trial can't reference a vendor that doesn't exist (FK constraint)."""
    gs = GoldSet(id=uuid.uuid4(), version=99999, description="test")
    db.add(gs)
    await db.flush()

    q = Question(
        id=uuid.uuid4(),
        gold_set_id=gs.id,
        key="q1",
        text="Test?",
        scoring_unit="entities",
        gold=[{"name": "A", "aliases": ["A"]}],
        verification="test",
    )
    db.add(q)
    await db.flush()

    r = Run(
        id=uuid.uuid4(),
        gold_set_id=gs.id,
        config={"medium": "none", "mode": "live", "vendors": ["fake"], "k": 5, "repeats": 1},
        code_version="abc123",
        status="pending",
    )
    db.add(r)
    await db.flush()

    # Try to create a trial pointing at a non-existent vendor
    t = Trial(
        id=uuid.uuid4(),
        run_id=r.id,
        question_id=q.id,
        vendor_id="nonexistent-vendor",  # doesn't exist
        repeat_index=1,
        status="pending",
    )
    db.add(t)
    with pytest.raises(IntegrityError, match="trials_vendor_id_fkey"):
        await db.flush()


async def test_gold_set_frozen_requires_frozen_at(db: AsyncSession):
    """A GoldSet with status='frozen' must have frozen_at set (CHECK constraint)."""
    gs = GoldSet(
        id=uuid.uuid4(),
        version=99999,
        description="test",
        status="frozen",
        frozen_at=None,  # missing
        content_hash="abc123",
    )
    db.add(gs)
    with pytest.raises(IntegrityError, match="ck_gold_sets_frozen_at"):
        await db.flush()
