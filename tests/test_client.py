"""Tests for VendorClient HTTP wrapper.

Tests the client's ability to send requests, inject auth headers, and measure latency.
All tests use mocked HTTP responses (no real network calls).
"""

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from searchdrift.client import VendorClient
from searchdrift.vendors.tavily import TavilyAdapter
from searchdrift.vendors.types import HttpRequest


@pytest.mark.asyncio
async def test_vendor_client_send_success():
    """VendorClient sends request and returns status, body, latency."""
    adapter = TavilyAdapter()
    client = VendorClient(adapter, api_key="test-key-123")

    request = HttpRequest(
        method="POST",
        url="https://api.tavily.com/search",
        headers={"Content-Type": "application/json"},
        body={"query": "test", "max_results": 5},
    )

    # Mock httpx response
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.text = '{"results": []}'

    with patch.object(client._client, "request", new_callable=AsyncMock) as mock_request:
        mock_request.return_value = mock_response

        status, body, latency = await client.send(request)

        assert status == 200
        assert body == '{"results": []}'
        assert latency >= 0  # Should be non-negative

        # Verify auth header was added
        call_args = mock_request.call_args
        assert "Authorization" in call_args.kwargs["headers"]
        assert call_args.kwargs["headers"]["Authorization"] == "Bearer test-key-123"


@pytest.mark.asyncio
async def test_vendor_client_timeout():
    """VendorClient raises timeout exception when request times out."""
    adapter = TavilyAdapter()
    client = VendorClient(adapter, api_key="test-key-123")

    request = HttpRequest(
        method="POST",
        url="https://api.tavily.com/search",
        headers={"Content-Type": "application/json"},
        body={"query": "test", "max_results": 5},
    )

    with patch.object(client._client, "request", new_callable=AsyncMock) as mock_request:
        mock_request.side_effect = httpx.TimeoutException("Request timed out")

        with pytest.raises(httpx.TimeoutException):
            await client.send(request)


@pytest.mark.asyncio
async def test_vendor_client_auth_header_format():
    """VendorClient calls adapter.add_auth_headers with correct arguments."""
    adapter = TavilyAdapter()
    client = VendorClient(adapter, api_key="secret-key")

    request = HttpRequest(
        method="POST",
        url="https://api.tavily.com/search",
        headers={"Content-Type": "application/json"},
        body={"query": "test"},
    )

    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.text = "{}"

    with patch.object(client._client, "request", new_callable=AsyncMock) as mock_request:
        mock_request.return_value = mock_response

        await client.send(request)

        # Verify the headers passed to httpx include auth
        call_args = mock_request.call_args
        headers = call_args.kwargs["headers"]
        assert headers["Content-Type"] == "application/json"
        assert headers["Authorization"] == "Bearer secret-key"


@pytest.mark.asyncio
async def test_vendor_client_context_manager():
    """VendorClient can be used as async context manager."""
    adapter = TavilyAdapter()

    async with VendorClient(adapter, api_key="test-key") as client:
        assert client._client is not None

    # After exiting context, client should be closed
    # (we can't easily test this without inspecting internal state)


@pytest.mark.asyncio
async def test_vendor_client_close():
    """VendorClient.close() closes the underlying httpx client."""
    adapter = TavilyAdapter()
    client = VendorClient(adapter, api_key="test-key")

    with patch.object(client._client, "aclose", new_callable=AsyncMock) as mock_close:
        await client.close()
        mock_close.assert_called_once()


@pytest.mark.asyncio
async def test_vendor_client_latency_measurement():
    """VendorClient measures latency in milliseconds."""
    adapter = TavilyAdapter()
    client = VendorClient(adapter, api_key="test-key")

    request = HttpRequest(
        method="POST",
        url="https://api.tavily.com/search",
        headers={},
        body={},
    )

    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.text = "{}"

    # Mock time.perf_counter to simulate 150ms delay
    with patch("searchdrift.client.time.perf_counter") as mock_time:
        mock_time.side_effect = [0.0, 0.150]  # start, end

        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response

            _, _, latency = await client.send(request)

            # Should be approximately 150ms
            assert 149 <= latency <= 151
