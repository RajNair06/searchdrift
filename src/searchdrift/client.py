"""HTTP client for calling vendor APIs.

This module wraps httpx with:
- Connection pooling (reuse TCP connections across calls)
- Timeouts (fail fast on slow vendors)
- Auth header injection (via adapter.add_auth_headers)
- Latency measurement (for cassette recording)

One VendorClient per vendor per run. Create at run start, close at run end.
"""

import time

import httpx

from searchdrift.vendors.types import HttpRequest, VendorAdapter


class VendorClient:
    """HTTP client for a specific vendor.
    
    Manages connection pooling, timeouts, and auth. The send() method
    handles the HTTP call and returns (status_code, response_body, latency_ms).
    
    Usage:
        adapter = get_adapter("tavily")
        client = VendorClient(adapter, api_key="tvly-...")
        
        request = adapter.build_request("Who created Python?", k=5)
        status, body, latency = await client.send(request)
        
        # Use body for parse_response
        results = adapter.parse_response(json.loads(body))
        
        await client.close()  # When done with the run
    """
    
    def __init__(
        self,
        adapter: VendorAdapter,
        api_key: str,
        timeout: float = 10.0,
        max_connections: int = 10,
    ):
        """Create a VendorClient.
        
        Args:
            adapter: The vendor adapter (for auth headers)
            api_key: The API key for this vendor
            timeout: Request timeout in seconds (default 10)
            max_connections: Max concurrent connections (default 10)
        """
        self.adapter = adapter
        self.api_key = api_key
        
        # httpx client with connection pooling
        self._client = httpx.AsyncClient(
            timeout=timeout,
            limits=httpx.Limits(max_connections=max_connections),
        )
    
    async def send(self, request: HttpRequest) -> tuple[int, str, int]:
        """Send an HTTP request and measure latency.
        
        Args:
            request: The request to send (method, url, headers, body)
        
        Returns:
            (status_code, response_body, latency_ms)
        
        Raises:
            httpx.TimeoutException: If the request times out
            httpx.RequestError: For connection failures
        """
        # Add auth headers (vendor-specific format)
        headers = self.adapter.add_auth_headers(request.headers, self.api_key)
        
        # Measure latency
        start = time.perf_counter()
        
        # Send the request
        response = await self._client.request(
            method=request.method,
            url=request.url,
            headers=headers,
            json=request.body,
        )
        
        end = time.perf_counter()
        latency_ms = int((end - start) * 1000)
        
        return response.status_code, response.text, latency_ms
    
    async def close(self):
        """Close the HTTP client and release connections."""
        await self._client.aclose()
    
    async def __aenter__(self):
        """Context manager entry."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - ensures client is closed."""
        await self.close()
