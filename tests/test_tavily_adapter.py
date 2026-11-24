"""Tests for the Tavily adapter.

These tests use fixture data (no network calls). They verify that:
1. build_request produces the right HTTP request shape
2. parse_response correctly translates Tavily's response into SearchResults
3. Edge cases like empty results are handled
"""

import pytest

from searchdrift.vendors.tavily import TavilyAdapter


class TestTavilyAdapter:
    """Test suite for TavilyAdapter."""

    def setup_method(self):
        """Create a fresh adapter for each test."""
        self.adapter = TavilyAdapter()

    def test_vendor_id(self):
        """Adapter exposes the correct vendor_id."""
        assert self.adapter.vendor_id == "tavily"

    def test_build_request(self):
        """build_request produces the right shape for Tavily's API."""
        request = self.adapter.build_request(query="Who created Python?", k=5)

        assert request.method == "POST"
        assert request.url == "https://api.tavily.com/search"
        assert request.headers == {"Content-Type": "application/json"}
        assert request.body == {
            "query": "Who created Python?",
            "max_results": 5,
        }

    def test_parse_response(self):
        """parse_response translates Tavily's response into SearchResults."""
        response = {
            "results": [
                {
                    "url": "https://docs.python.org/3/faq/general.html",
                    "title": "General Python FAQ",
                    "content": "Guido van Rossum created Python...",
                },
                {
                    "url": "https://en.wikipedia.org/wiki/Guido_van_Rossum",
                    "title": "Guido van Rossum - Wikipedia",
                    "content": "Guido van Rossum is a Dutch programmer...",
                },
            ]
        }

        results = self.adapter.parse_response(response)

        assert len(results) == 2
        assert results[0].rank == 1
        assert results[0].url == "https://docs.python.org/3/faq/general.html"
        assert results[0].title == "General Python FAQ"
        assert results[0].text == "Guido van Rossum created Python..."

        assert results[1].rank == 2
        assert results[1].url == "https://en.wikipedia.org/wiki/Guido_van_Rossum"

    def test_parse_response_empty(self):
        """parse_response handles empty results gracefully."""
        response = {"results": []}

        results = self.adapter.parse_response(response)

        assert results == []

    def test_parse_response_missing_fields(self):
        """parse_response raises KeyError if response is malformed."""
        response = {"results": [{"url": "https://example.com"}]}  # missing title, content

        with pytest.raises(KeyError):
            self.adapter.parse_response(response)

    def test_add_auth_headers(self):
        """add_auth_headers adds Bearer token in Tavily's format."""
        headers = {"Content-Type": "application/json"}
        api_key = "tvly-test-key-123"

        result = self.adapter.add_auth_headers(headers, api_key)

        assert result == {
            "Content-Type": "application/json",
            "Authorization": "Bearer tvly-test-key-123",
        }
        # Original headers should not be modified
        assert headers == {"Content-Type": "application/json"}
