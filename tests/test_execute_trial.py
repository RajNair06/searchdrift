"""Tests for the execute_trial gate function.

Tests both live mode (send + record) and replay mode (find cassette).
All HTTP calls are mocked - no real network traffic.
"""

import json
import uuid
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from searchdrift.cassette import execute_trial, hash_request
from searchdrift.client import VendorClient
from searchdrift.models import Cassette, GoldSet, Question, Run, Trial, Vendor
from searchdrift.vendors.tavily import TavilyAdapter

# ---------------------------------------------------------------------------
# Live mode tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_trial_live_success(db: AsyncSession):
    """Live mode: sends request, records cassette, returns success."""
    # Set up vendor
    vendor = Vendor(
        id="tavily-live-success",
        enabled=True,
        budget_calls=1000,
        budget_period="monthly",
    )
    db.add(vendor)
    await db.flush()

    adapter = TavilyAdapter()
    client = VendorClient(adapter, api_key="test-key")

    # Mock the HTTP response
    mock_response_body = json.dumps({
        "results": [
            {"url": "https://example.com", "title": "Example", "content": "text"},
        ]
    })

    with patch.object(client._client, "request", new_callable=AsyncMock) as mock_req:
        mock_http_resp = AsyncMock()
        mock_http_resp.status_code = 200
        mock_http_resp.text = mock_response_body
        mock_req.return_value = mock_http_resp

        result = await execute_trial(
            db=db,
            adapter=adapter,
            question_text="Who created Python?",
            vendor_id="tavily-live-success",
            repeat_index=1,
            k=5,
            client=client,
            replay_from_run_id=None,  # Live mode
        )

    assert result.was_replay is False
    assert result.error_kind is None
    assert result.error is None
    assert result.cassette is not None
    assert result.cassette.vendor_id == "tavily-live-success"
    assert result.cassette.status_code == 200
    assert result.cassette.response_body == mock_response_body
    assert result.cassette.latency_ms >= 0


@pytest.mark.asyncio
async def test_execute_trial_live_timeout(db: AsyncSession):
    """Live mode: timeout returns error with error_kind='timeout'."""
    vendor = Vendor(
        id="tavily-live-timeout",
        enabled=True,
        budget_calls=1000,
        budget_period="monthly",
    )
    db.add(vendor)
    await db.flush()

    adapter = TavilyAdapter()
    client = VendorClient(adapter, api_key="test-key")

    with patch.object(client._client, "request", new_callable=AsyncMock) as mock_req:
        mock_req.side_effect = httpx.TimeoutException("Connection timed out")

        result = await execute_trial(
            db=db,
            adapter=adapter,
            question_text="test query",
            vendor_id="tavily-live-timeout",
            repeat_index=1,
            client=client,
        )

    assert result.was_replay is False
    assert result.cassette is None
    assert result.error_kind == "timeout"
    assert "timed out" in result.error


@pytest.mark.asyncio
async def test_execute_trial_live_connection_error(db: AsyncSession):
    """Live mode: connection failure returns error with error_kind='http_error'."""
    vendor = Vendor(
        id="tavily-live-connerr",
        enabled=True,
        budget_calls=1000,
        budget_period="monthly",
    )
    db.add(vendor)
    await db.flush()

    adapter = TavilyAdapter()
    client = VendorClient(adapter, api_key="test-key")

    with patch.object(client._client, "request", new_callable=AsyncMock) as mock_req:
        mock_req.side_effect = httpx.ConnectError("Connection refused")

        result = await execute_trial(
            db=db,
            adapter=adapter,
            question_text="test query",
            vendor_id="tavily-live-connerr",
            repeat_index=1,
            client=client,
        )

    assert result.was_replay is False
    assert result.cassette is None
    assert result.error_kind == "http_error"


@pytest.mark.asyncio
async def test_execute_trial_live_http_500(db: AsyncSession):
    """Live mode: vendor returns 500, cassette is recorded but trial has error."""
    vendor = Vendor(
        id="tavily-live-500",
        enabled=True,
        budget_calls=1000,
        budget_period="monthly",
    )
    db.add(vendor)
    await db.flush()

    adapter = TavilyAdapter()
    client = VendorClient(adapter, api_key="test-key")

    with patch.object(client._client, "request", new_callable=AsyncMock) as mock_req:
        mock_http_resp = AsyncMock()
        mock_http_resp.status_code = 500
        mock_http_resp.text = '{"error": "internal server error"}'
        mock_req.return_value = mock_http_resp

        result = await execute_trial(
            db=db,
            adapter=adapter,
            question_text="test query",
            vendor_id="tavily-live-500",
            repeat_index=1,
            client=client,
        )

    # Cassette is recorded even on HTTP error
    assert result.cassette is not None
    assert result.cassette.status_code == 500
    assert result.was_replay is False
    assert result.error_kind == "http_error"
    assert "500" in result.error


@pytest.mark.asyncio
async def test_execute_trial_live_no_client_raises(db: AsyncSession):
    """Live mode without a client raises ValueError."""
    adapter = TavilyAdapter()

    with pytest.raises(ValueError, match="Live mode requires a VendorClient"):
        await execute_trial(
            db=db,
            adapter=adapter,
            question_text="test query",
            vendor_id="tavily",
            repeat_index=1,
            client=None,
            replay_from_run_id=None,
        )


# ---------------------------------------------------------------------------
# Replay mode tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_trial_replay_hit(db: AsyncSession):
    """Replay mode: finds cassette from source run, returns it."""
    # Set up prerequisite data
    vendor = Vendor(
        id="tavily-replay-hit",
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
        key="python-creator",
        text="Who created Python?",
        scoring_unit="entities",
        gold=[{"name": "Guido van Rossum", "aliases": ["GvRS"]}],
        verification="manual",
    )
    db.add(question)
    await db.flush()

    source_run = Run(
        id=uuid.uuid4(),
        gold_set_id=gold_set.id,
        status="completed",
        config={"mode": "live", "repeats": 3},
        code_version="abc123",
    )
    db.add(source_run)
    await db.flush()

    # Build the same request that execute_trial will build
    adapter = TavilyAdapter()
    request = adapter.build_request(query="Who created Python?", k=5)
    request_hash = hash_request(request)

    # Create a cassette in the source run
    cassette = Cassette(
        id=uuid.uuid4(),
        vendor_id="tavily-replay-hit",
        request_hash=request_hash,
        request=request.model_dump(),
        status_code=200,
        response_body=(
            '{"results": [{"url": "https://example.com",'
            ' "title": "Python", "content": "Guido"}]}'
        ),
        latency_ms=120,
    )
    db.add(cassette)
    await db.flush()

    # Create a trial in the source run that links to this cassette
    source_trial = Trial(
        id=uuid.uuid4(),
        run_id=source_run.id,
        question_id=question.id,
        vendor_id="tavily-replay-hit",
        repeat_index=2,
        status="succeeded",
        cassette_id=cassette.id,
    )
    db.add(source_trial)
    await db.flush()

    # Now replay from the source run
    result = await execute_trial(
        db=db,
        adapter=adapter,
        question_text="Who created Python?",
        vendor_id="tavily-replay-hit",
        repeat_index=2,
        k=5,
        replay_from_run_id=source_run.id,
    )

    assert result.was_replay is True
    assert result.error_kind is None
    assert result.error is None
    assert result.cassette is not None
    assert result.cassette.id == cassette.id
    expected_body = (
        '{"results": [{"url": "https://example.com",'
        ' "title": "Python", "content": "Guido"}]}'
    )
    assert result.cassette.response_body == expected_body


@pytest.mark.asyncio
async def test_execute_trial_replay_miss(db: AsyncSession):
    """Replay mode: no cassette found, returns error with error_kind='replay_miss'."""
    adapter = TavilyAdapter()
    nonexistent_run_id = uuid.uuid4()

    result = await execute_trial(
        db=db,
        adapter=adapter,
        question_text="Who created Python?",
        vendor_id="tavily-replay-miss",
        repeat_index=1,
        k=5,
        replay_from_run_id=nonexistent_run_id,
    )

    assert result.was_replay is True
    assert result.cassette is None
    assert result.error_kind == "replay_miss"
    assert "No cassette found" in result.error


@pytest.mark.asyncio
async def test_execute_trial_replay_ignores_client(db: AsyncSession):
    """Replay mode ignores the client even if one is provided."""
    adapter = TavilyAdapter()
    # Create a client that would fail if used
    client = VendorClient(adapter, api_key="should-not-be-used")
    nonexistent_run_id = uuid.uuid4()

    result = await execute_trial(
        db=db,
        adapter=adapter,
        question_text="test query",
        vendor_id="tavily",
        repeat_index=1,
        client=client,
        replay_from_run_id=nonexistent_run_id,
    )

    # Should be replay_miss, not an HTTP error (client was not used)
    assert result.was_replay is True
    assert result.error_kind == "replay_miss"
