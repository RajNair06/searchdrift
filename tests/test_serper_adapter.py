"""Tests for the Serper adapter.

These tests use fixture data (no network calls). They verify that:
1. build_request produces the right HTTP request shape for Serper
2. parse_response correctly translates Serper's different field names into SearchResults
3. Edge cases like empty results are handled
"""

import pytest

from searchdrift.vendors.serper import SerperAdapter


class TestSerperAdapter:
    """Test suite for SerperAdapter."""

    def setup_method(self):
        """Create a fresh adapter for each test."""
        self.adapter = SerperAdapter()

    def test_vendor_id(self):
        """Adapter exposes the correct vendor_id."""
        assert self.adapter.vendor_id == "serper"

    def test_build_request(self):
        """build_request produces the right shape for Serper's API."""
        request = self.adapter.build_request(query="Who created Python?", k=5)

        assert request.method == "POST"
        assert request.url == "https://google.serper.dev/search"
        assert request.headers == {"Content-Type": "application/json"}
        assert request.body == {
            "q": "Who created Python?",
            "num": 5,
        }

    def test_parse_response(self):
        """parse_response translates Serper's response into SearchResults.

        Serper uses different field names (organic, link, snippet) which
        the adapter normalizes into our common SearchResult shape.
        """
        response = {
            "organic": [
                {
                    "link": "https://docs.python.org/3/faq/general.html",
                    "title": "General Python FAQ",
                    "snippet": "Guido van Rossum created Python...",
                },
                {
                    "link": "https://en.wikipedia.org/wiki/Guido_van_Rossum",
                    "title": "Guido van Rossum - Wikipedia",
                    "snippet": "Guido van Rossum is a Dutch programmer...",
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
        response = {"organic": []}

        results = self.adapter.parse_response(response)

        assert results == []

    def test_parse_response_missing_fields(self):
        """parse_response raises KeyError if response is malformed."""
        response = {"organic": [{"link": "https://example.com"}]}  # missing title, snippet

        with pytest.raises(KeyError):
            self.adapter.parse_response(response)

    def test_add_auth_headers(self):
        """add_auth_headers adds X-API-KEY header in Serper's format."""
        headers = {"Content-Type": "application/json"}
        api_key = "serper-test-key-123"

        result = self.adapter.add_auth_headers(headers, api_key)

        assert result == {
            "Content-Type": "application/json",
            "X-API-KEY": "serper-test-key-123",
        }
        # Original headers should not be modified
        assert headers == {"Content-Type": "application/json"}
