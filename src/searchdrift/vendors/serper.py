"""Serper adapter: translates between Serper's API and our common interface.

Serper's API (Google Search results) has very different field names:
- "q" instead of "query"
- "num" instead of "max_results" or "numResults"
- "organic" instead of "results"
- "link" instead of "url"
- "snippet" instead of "content" or "text"

This adapter normalizes Serper's response into our common SearchResult shape.
Without adapters, the scoring layer would need vendor-specific code for each
field name — exactly the coupling the adapter pattern eliminates.
"""

from searchdrift.vendors.types import HttpRequest, SearchResult


class SerperAdapter:
    """Adapter for Serper's search API (google.serper.dev).

    Serper's response format:
    {
      "organic": [
        {
          "link": "https://example.com",
          "title": "Example Title",
          "snippet": "Snippet text here...",
          ...
        },
        ...
      ]
    }

    Note: Serper returns results in an "organic" array (not "results"),
    and uses "link" for URLs and "snippet" for text.
    """

    @property
    def vendor_id(self) -> str:
        return "serper"

    def build_request(self, query: str, k: int) -> HttpRequest:
        """Build the HTTP request for Serper's search endpoint.

        Serper expects:
        - POST to https://google.serper.dev/search
        - JSON body with "q" and "num"

        Args:
            query: the search query
            k: number of results to request

        Returns:
            HttpRequest ready to be hashed and sent
        """
        return HttpRequest(
            method="POST",
            url="https://google.serper.dev/search",
            headers={"Content-Type": "application/json"},
            body={
                "q": query,
                "num": k,
            },
        )

    def parse_response(self, response: dict) -> list[SearchResult]:
        """Parse Serper's response into normalized SearchResults.

        Serper returns:
        {
          "organic": [
            {"link": "...", "title": "...", "snippet": "...", ...},
            ...
          ]
        }

        We extract link (→ url), title, and snippet (→ text), adding a rank.

        Args:
            response: Serper's JSON response as a dict

        Returns:
            List of SearchResult

        Raises:
            KeyError: if response is missing expected fields
        """
        results = []
        for i, item in enumerate(response["organic"], start=1):
            results.append(
                SearchResult(
                    rank=i,
                    url=item["link"],
                    title=item["title"],
                    text=item["snippet"],
                )
            )
        return results

    def add_auth_headers(self, headers: dict[str, str], api_key: str) -> dict[str, str]:
        """Add Serper's API key to headers.

        Serper uses: X-API-KEY: <key>
        """
        return {**headers, "X-API-KEY": api_key}
