"""Verification: tests run with zero network access.

This test explicitly verifies that no vendor API keys are set in the
**environment variables**. This is the "replay-only" guarantee: tests
cannot make real network calls because they have no keys to authenticate with.

Why this matters:
- Real calls cost money (credits are finite)
- Real calls are flaky (vendor responses vary)
- Real calls are slow (network latency)

In CI, we never set TAVILY_API_KEY, EXA_API_KEY, or SERPER_API_KEY in the
environment, and there is no .env file. This test fails if someone accidentally
adds them to CI secrets, catching the bug before it costs credits.

Locally, .env has keys for development — that's expected and fine. This test
checks the raw environment (which is what CI controls), not .env.
"""

import os


def test_no_vendor_api_keys_in_environment():
    """No vendor API keys in the environment (replay-only guarantee).

    This test documents the guarantee: in CI, no test should have access to
    vendor API keys. If this test fails in CI, someone added keys to the
    CI secrets — which means tests could accidentally make real network calls.

    Locally this test may pass or fail depending on your .env — that's fine.
    The .env file is a local convenience; CI never has one.
    """
    # os.environ is what CI controls. .env is a local-only convenience.
    for key in ("TAVILY_API_KEY", "EXA_API_KEY", "SERPER_API_KEY"):
        assert key not in os.environ, (
            f"{key} is set in the environment — CI should run without vendor keys"
        )
