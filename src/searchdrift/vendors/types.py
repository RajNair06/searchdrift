"""Shared types for vendor adapters.

This module defines the contract that every vendor adapter must satisfy:
- SearchResult: a normalized search result we can score
- HttpRequest: the HTTP request we'd send to the vendor
- VendorAdapter: the interface every adapter implements

The adapter pattern (from Design Patterns, Gamma et al.) lets the rest of the
system talk to any vendor the same way. The Trial code doesn't know or care
whether it's talking to Tavily or Exa — it just calls build_request() and
parse_response().
"""

from typing import Protocol

from pydantic import BaseModel


class SearchResult(BaseModel):
    """One search result, normalized across all vendors.

    This is what we compare against the gold answer during scoring. Every
    vendor returns a list of these, regardless of how they name their fields.

    Fields:
    - rank: 1-based position in the results (1 = top result)
    - url: the result's URL
    - title: the result's title/headline
    - text: the snippet or extract (what we search for entity mentions)
    """

    rank: int
    url: str
    title: str
    text: str


class HttpRequest(BaseModel):
    """The HTTP request we'd send to a vendor.

    Adapters build this; the cassette layer hashes it for deduplication, then
    httpx sends it. The API key is added by the cassette layer, not the adapter
    (so the key doesn't leak into cassettes).

    Fields:
    - method: HTTP method (always POST for search APIs)
    - url: the full endpoint URL
    - headers: request headers (no API key)
    - body: the JSON body as a dict
    """

    method: str
    url: str
    headers: dict[str, str]
    body: dict


class VendorAdapter(Protocol):
    """The interface every vendor adapter must implement.

    This is a Protocol (structural subtyping), not an ABC. That means adapters
    don't need to inherit from it — they just need to have the right methods
    with the right signatures. Python's type checker (mypy) verifies this.

    Why Protocol over ABC:
    - No inheritance coupling
    - Adapters can be tested in isolation
    - The type system enforces the contract without runtime overhead
    """

    @property
    def vendor_id(self) -> str:
        """Unique identifier for this vendor (matches the Vendor row ID)."""
        ...

    def build_request(self, query: str, k: int) -> HttpRequest:
        """Build the HTTP request for a search query.

        Args:
            query: the search query string
            k: number of results to request

        Returns:
            HttpRequest ready to be hashed and sent
        """
        ...

    def parse_response(self, response: dict) -> list[SearchResult]:
        """Parse a vendor's JSON response into normalized SearchResults.

        Args:
            response: the JSON response body as a dict

        Returns:
            List of SearchResult, one per result in the response

        Raises:
            KeyError, ValueError: if the response is malformed
        """
        ...

    def add_auth_headers(self, headers: dict[str, str], api_key: str) -> dict[str, str]:
        """Add the API key to request headers in vendor-specific format.

        Each vendor uses a different header name for the API key:
        - Tavily: Authorization: Bearer <key>
        - Exa: x-api-key: <key>
        - Serper: X-API-KEY: <key>

        This method keeps auth logic in the adapter where vendor knowledge belongs.

        Args:
            headers: The base headers from build_request()
            api_key: The API key to add

        Returns:
            A new dict with the auth header added
        """
        ...
