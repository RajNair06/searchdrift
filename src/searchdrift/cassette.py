"""Cassette layer: record and replay vendor calls.

This module handles:
1. Request hashing - stable fingerprint for deduplication
2. Recording live responses to the cassettes table
3. Replaying from cassettes (no network, no credits)
4. The send gate - orchestrate build → hash → record/replay

Every vendor call goes through this layer. Nothing bypasses it.
"""

import hashlib
import json
from dataclasses import dataclass
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from searchdrift.client import VendorClient
from searchdrift.models import Cassette, Trial
from searchdrift.vendors.types import HttpRequest, VendorAdapter


@dataclass
class ExecuteResult:
    """Result of executing a trial.

    Attributes:
        cassette: The cassette (recorded or replayed). None on failure.
        was_replay: True if the result came from a cassette, False if from a live call.
        error_kind: None on success. One of: "replay_miss", "timeout",
                    "http_error", "parse_error" on failure.
        error: Human-readable error message. None on success.
    """

    cassette: Cassette | None
    was_replay: bool
    error_kind: str | None = None
    error: str | None = None


def hash_request(request: HttpRequest) -> str:
    """Create a stable SHA-256 hash of an HTTP request.

    The hash is a fingerprint: same request → same hash, every time.
    This is the cassette key for deduplication and replay.

    Args:
        request: The HTTP request to hash (method, URL, headers, body)

    Returns:
        A string like "v1|abc123def456..." (version prefix + hex digest)

    Why canonical JSON?
        JSON key order doesn't matter semantically, but it changes the hash.
        We sort keys and remove whitespace so {"a":1,"b":2} and {"b":2,"a":1}
        produce the same hash.

    Why exclude the API key?
        The API key is added by VendorClient just before sending, not included
        in the HttpRequest. This way, rotating keys doesn't change hashes and
        orphan the entire cassette library.

    Why the version prefix?
        If we ever change the hash algorithm (e.g., SHA-3, or include more fields),
        old and new hashes can't silently collide. We bump to "v2|" and both
        generations coexist.
    """
    # Convert request to dict, sort keys, remove whitespace
    canonical = json.dumps(
        request.model_dump(),
        sort_keys=True,
        separators=(",", ":"),
    )
    
    # SHA-256 hash of the canonical JSON
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    
    # Version prefix for future-proofing
    return f"v1|{digest}"


async def find_cassette(
    db: AsyncSession,
    vendor_id: str,
    request_hash: str,
    source_run_id: UUID,
    repeat_index: int,
) -> Cassette | None:
    """Find the cassette from a specific source trial (for replay).

    Replay rule: each trial replays exactly what the matching source trial got.
    This reproduces the original measurement deterministically, including the
    vendor's noise across repeats.

    Args:
        db: Database session
        vendor_id: Which vendor (e.g., "tavily")
        request_hash: The hash of the request we're replaying
        source_run_id: The run ID to replay from
        repeat_index: Which repeat (1, 2, or 3)

    Returns:
        The cassette if found, None if not (replay miss)

    Example:
        # Replaying trial: tavily, question "Who created Python?", repeat 2
        cassette = await find_cassette(
            db,
            vendor_id="tavily",
            request_hash="v1|abc123...",
            source_run_id=baseline_run.id,
            repeat_index=2,
        )
        if cassette is None:
            # Replay miss - no recording for this trial in the source run
            trial.status = "failed"
            trial.error_kind = "replay_miss"
    """
    # Find the trial from the source run that matches our criteria
    query = (
        select(Cassette)
        .join(Trial, Trial.cassette_id == Cassette.id)
        .where(
            Trial.run_id == source_run_id,
            Trial.vendor_id == vendor_id,
            Trial.repeat_index == repeat_index,
            Cassette.request_hash == request_hash,
        )
    )
    
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def record_cassette(
    db: AsyncSession,
    vendor_id: str,
    request: HttpRequest,
    request_hash: str,
    status_code: int,
    response_body: str,
    latency_ms: int,
) -> Cassette:
    """Record a live vendor response as a new cassette.

    Cassettes are append-only: every live call inserts a new row. The same
    request_hash can appear many times (3 repeats in one run, nightly runs
    over weeks). We never overwrite.

    Args:
        db: Database session
        vendor_id: Which vendor (e.g., "tavily")
        request: The HTTP request we sent (for debugging and hash verification)
        request_hash: The hash we computed (stored for fast lookups)
        status_code: HTTP status (200, 404, 500, etc.)
        response_body: The raw response body as text (preserves exact bytes)
        latency_ms: How long the vendor took to respond

    Returns:
        The created cassette

    Why store the full request?
        For debugging: "what did we actually send?" And for hash verification:
        we can recompute the hash and confirm it matches request_hash.

    Why response_body is TEXT, not JSONB?
        JSONB parses and reorders keys. If a vendor changes key order between
        calls, JSONB would normalize them, breaking reproducibility. TEXT
        preserves the exact bytes.
    """
    cassette = Cassette(
        vendor_id=vendor_id,
        request=request.model_dump(),
        request_hash=request_hash,
        status_code=status_code,
        response_body=response_body,
        latency_ms=latency_ms,
    )
    
    db.add(cassette)
    await db.flush()  # Get the cassette.id back
    
    return cassette


async def execute_trial(
    db: AsyncSession,
    adapter: VendorAdapter,
    question_text: str,
    vendor_id: str,
    repeat_index: int,
    k: int = 5,
    client: VendorClient | None = None,
    replay_from_run_id: UUID | None = None,
) -> ExecuteResult:
    """Execute one trial: build request → hash → replay or send live → record.

    This is the single gate for all vendor calls. Every trial goes through
    this function, never directly to the network.

    Two modes:
    - Replay (replay_from_run_id is set): find the cassette from a previous run.
      No network, no credits. If the cassette is missing, the trial fails with
      error_kind="replay_miss".
    - Live (replay_from_run_id is None): send the request via VendorClient,
      record the response as a new cassette. Requires a client.

    Args:
        db: Database session
        adapter: The vendor adapter (for building requests)
        question_text: The question to search for
        vendor_id: Which vendor (e.g., "tavily")
        repeat_index: Which repeat (1, 2, or 3)
        k: Number of results to request (default 5)
        client: VendorClient for live calls. Required in live mode, ignored in
                replay mode.
        replay_from_run_id: If set, replay from this run's cassettes instead
                            of making live calls.

    Returns:
        ExecuteResult with either a cassette (success) or error info (failure)

    Why separate modes?
        Baseline runs make live calls and record cassettes. Drift runs replay
        from the baseline. This separation is what makes drift detection
        reproducible: the same cassette = the same vendor response = the same
        score.

    Why error responses still get recorded?
        If a vendor returns 429 or 500, we still spent a credit and got a
        response. Recording it lets us replay the error later (useful for
        testing) and keeps the cassette library complete.
    """
    # Step 1: Build the request from the adapter
    request = adapter.build_request(query=question_text, k=k)

    # Step 2: Hash the request (stable fingerprint)
    request_hash = hash_request(request)

    # Step 3: Replay mode - look for an existing cassette
    if replay_from_run_id is not None:
        cassette = await find_cassette(
            db=db,
            vendor_id=vendor_id,
            request_hash=request_hash,
            source_run_id=replay_from_run_id,
            repeat_index=repeat_index,
        )

        if cassette is not None:
            return ExecuteResult(
                cassette=cassette,
                was_replay=True,
            )

        # Replay miss - no cassette recorded for this trial in the source run
        return ExecuteResult(
            cassette=None,
            was_replay=True,
            error_kind="replay_miss",
            error=f"No cassette found for replay (run={replay_from_run_id}, "
                  f"vendor={vendor_id}, repeat={repeat_index})",
        )

    # Step 4: Live mode - send the request and record the response
    if client is None:
        raise ValueError("Live mode requires a VendorClient. Pass client=...")

    try:
        status_code, response_body, latency_ms = await client.send(request)
    except httpx.TimeoutException as exc:
        return ExecuteResult(
            cassette=None,
            was_replay=False,
            error_kind="timeout",
            error=str(exc),
        )
    except httpx.HTTPError as exc:
        return ExecuteResult(
            cassette=None,
            was_replay=False,
            error_kind="http_error",
            error=str(exc),
        )

    # Record the cassette (even if the vendor returned an error status)
    cassette = await record_cassette(
        db=db,
        vendor_id=vendor_id,
        request=request,
        request_hash=request_hash,
        status_code=status_code,
        response_body=response_body,
        latency_ms=latency_ms,
    )

    # Check if the vendor returned an HTTP error
    if status_code >= 400:
        return ExecuteResult(
            cassette=cassette,
            was_replay=False,
            error_kind="http_error",
            error=f"Vendor returned HTTP {status_code}",
        )

    return ExecuteResult(
        cassette=cassette,
        was_replay=False,
    )
