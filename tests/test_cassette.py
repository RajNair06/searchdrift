"""Tests for cassette layer functions.

Tests hash_request, find_cassette, and record_cassette without making
real HTTP calls.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from searchdrift.cassette import find_cassette, hash_request, record_cassette
from searchdrift.models import GoldSet, Question, Run, Trial, Vendor
from searchdrift.vendors.types import HttpRequest


def test_hash_request_deterministic():
    """Same request always produces the same hash."""
    request = HttpRequest(
        method="POST",
        url="https://api.tavily.com/search",
        headers={"Content-Type": "application/json"},
        body={"query": "Who created Python?", "max_results": 5},
    )

    hash1 = hash_request(request)
    hash2 = hash_request(request)

    assert hash1 == hash2
    assert hash1.startswith("v1|")


def test_hash_request_canonical_json():
    """JSON key order doesn't affect the hash."""
    # Same data, different key order
    request1 = HttpRequest(
        method="POST",
        url="https://api.tavily.com/search",
        headers={"Content-Type": "application/json"},
        body={"query": "test", "max_results": 5},
    )
    request2 = HttpRequest(
        method="POST",
        url="https://api.tavily.com/search",
        headers={"Content-Type": "application/json"},
        body={"max_results": 5, "query": "test"},  # Different order
    )

    assert hash_request(request1) == hash_request(request2)


def test_hash_request_different_queries():
    """Different queries produce different hashes."""
    request1 = HttpRequest(
        method="POST",
        url="https://api.tavily.com/search",
        headers={"Content-Type": "application/json"},
        body={"query": "Who created Python?", "max_results": 5},
    )
    request2 = HttpRequest(
        method="POST",
        url="https://api.tavily.com/search",
        headers={"Content-Type": "application/json"},
        body={"query": "What is asyncio?", "max_results": 5},
    )

    assert hash_request(request1) != hash_request(request2)


def test_hash_request_different_vendors():
    """Same query to different vendors produces different hashes."""
    request_tavily = HttpRequest(
        method="POST",
        url="https://api.tavily.com/search",
        headers={"Content-Type": "application/json"},
        body={"query": "test", "max_results": 5},
    )
    request_exa = HttpRequest(
        method="POST",
        url="https://api.exa.ai/search",
        headers={"Content-Type": "application/json"},
        body={"query": "test", "numResults": 5, "contents": {"text": True}},
    )

    assert hash_request(request_tavily) != hash_request(request_exa)


def test_hash_request_header_order():
    """Header order doesn't affect the hash."""
    request1 = HttpRequest(
        method="POST",
        url="https://api.tavily.com/search",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        body={"query": "test"},
    )
    request2 = HttpRequest(
        method="POST",
        url="https://api.tavily.com/search",
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        body={"query": "test"},
    )

    assert hash_request(request1) == hash_request(request2)


# Database-dependent tests for find_cassette and record_cassette


@pytest.mark.asyncio
async def test_record_cassette(db: AsyncSession):
    """record_cassette creates a cassette with all fields."""
    # First create the vendor
    vendor = Vendor(
        id="tavily-record-test",
        enabled=True,
        budget_calls=1000,
        budget_period="monthly",
    )
    db.add(vendor)
    await db.flush()

    request = HttpRequest(
        method="POST",
        url="https://api.tavily.com/search",
        headers={"Content-Type": "application/json"},
        body={"query": "test", "max_results": 5},
    )
    request_hash = hash_request(request)

    cassette = await record_cassette(
        db=db,
        vendor_id="tavily-record-test",
        request=request,
        request_hash=request_hash,
        status_code=200,
        response_body='{"results": []}',
        latency_ms=150,
    )

    # Verify the cassette was created
    assert cassette.id is not None
    assert cassette.vendor_id == "tavily-record-test"
    assert cassette.request_hash == request_hash
    assert cassette.status_code == 200
    assert cassette.response_body == '{"results": []}'
    assert cassette.latency_ms == 150
    assert cassette.recorded_at is not None


@pytest.mark.asyncio
async def test_find_cassette_found(db: AsyncSession):
    """find_cassette returns the cassette when it exists."""
    # Create prerequisite data
    vendor = Vendor(
        id="tavily-find-test",
        enabled=True,
        budget_calls=1000,
        budget_period="monthly",
    )
    db.add(vendor)
    await db.flush()

    gold_set = GoldSet(
        id=uuid.uuid4(),
        version=99999,
        description="test",
        status="draft",
    )
    db.add(gold_set)
    await db.flush()

    question = Question(
        id=uuid.uuid4(),
        gold_set_id=gold_set.id,
        key="test-question",
        text="test question",
        scoring_unit="entities",
        gold=[{"name": "answer", "aliases": ["answer"]}],
        verification="test verification",
    )
    db.add(question)
    await db.flush()

    run = Run(
        id=uuid.uuid4(),
        gold_set_id=gold_set.id,
        status="pending",
        config={"mode": "live", "repeats": 1},
        code_version="test-version",
    )
    db.add(run)
    await db.flush()

    # Create a cassette
    request = HttpRequest(
        method="POST",
        url="https://api.tavily.com/search",
        headers={"Content-Type": "application/json"},
        body={"query": "test", "max_results": 5},
    )
    request_hash = hash_request(request)

    cassette = await record_cassette(
        db=db,
        vendor_id="tavily-find-test",
        request=request,
        request_hash=request_hash,
        status_code=200,
        response_body='{"results": []}',
        latency_ms=150,
    )

    # Create a trial that uses this cassette
    trial = Trial(
        id=uuid.uuid4(),
        run_id=run.id,
        question_id=question.id,
        vendor_id="tavily-find-test",
        repeat_index=1,
        status="succeeded",
        cassette_id=cassette.id,
    )
    db.add(trial)
    await db.flush()

    # Now try to find it
    found = await find_cassette(
        db=db,
        vendor_id="tavily-find-test",
        request_hash=request_hash,
        source_run_id=run.id,
        repeat_index=1,
    )

    assert found is not None
    assert found.id == cassette.id


@pytest.mark.asyncio
async def test_find_cassette_not_found(db: AsyncSession):
    """find_cassette returns None when cassette doesn't exist."""
    source_run_id = uuid.uuid4()
    request_hash = "v1|nonexistent"

    found = await find_cassette(
        db=db,
        vendor_id="tavily",
        request_hash=request_hash,
        source_run_id=source_run_id,
        repeat_index=1,
    )

    assert found is None
