"""Vendor adapters: translates between vendor-specific APIs and our common interface.

This package provides adapters for three search vendors (Tavily, Exa, Serper)
that implement the VendorAdapter protocol. Each adapter:
- Builds an HttpRequest with the vendor's expected format
- Parses the vendor's response into normalized SearchResults

The adapter pattern lets the rest of the system talk to any vendor the same
way — the Trial code doesn't know or care whether it's talking to Tavily or Exa.

Usage:
    from searchdrift.vendors import get_adapter

    adapter = get_adapter("tavily")
    request = adapter.build_request("Who created Python?", k=5)
    results = adapter.parse_response(response_json)
"""

from searchdrift.vendors.exa import ExaAdapter
from searchdrift.vendors.serper import SerperAdapter
from searchdrift.vendors.tavily import TavilyAdapter
from searchdrift.vendors.types import HttpRequest, SearchResult, VendorAdapter

# Registry of adapter instances, keyed by vendor_id.
# Add new adapters here as they're implemented.
_ADAPTERS: dict[str, VendorAdapter] = {
    "tavily": TavilyAdapter(),
    "exa": ExaAdapter(),
    "serper": SerperAdapter(),
}


def get_adapter(vendor_id: str) -> VendorAdapter:
    """Get the adapter for a given vendor_id.

    Args:
        vendor_id: the vendor's unique identifier (e.g., "tavily", "exa", "serper")

    Returns:
        The adapter instance for that vendor

    Raises:
        KeyError: if vendor_id is not registered

    Example:
        >>> adapter = get_adapter("tavily")
        >>> adapter.vendor_id
        'tavily'
    """
    if vendor_id not in _ADAPTERS:
        raise KeyError(
            f"No adapter registered for vendor '{vendor_id}'. "
            f"Available: {list(_ADAPTERS.keys())}"
        )
    return _ADAPTERS[vendor_id]


__all__ = [
    "HttpRequest",
    "SearchResult",
    "VendorAdapter",
    "get_adapter",
]
