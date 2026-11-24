"""Tavily adapter: translates between Tavily's API and our common interface.

Tavily's search API returns results in a specific format. This adapter:
1. Builds an HttpRequest with Tavily's expected body shape
2. Parses Tavily's response into our normalized SearchResult list

The adapter never touches the network — it only translates data shapes. The
cassette layer (built next) handles hashing, rate limiting, and sending.
"""

from searchdrift.vendors.types import HttpRequest, SearchResult


class TavilyAdapter:
    """Adapter for Tavily's search API (api.tavily.com).

    Tavily's response format:
    {
      "results": [
        {
          "url": "https://example.com",
          "title": "Example Title",
          "content": "Snippet text here...",
          ...
        },
        ...
      ]
    }

    We normalize this into SearchResult(rank=1, url=..., title=..., text=...).
    """

    @property
    def vendor_id(self) -> str:
        return "tavily"

    def build_request(self, query: str, k: int) -> HttpRequest:
        """Build the HTTP request for Tavily's search endpoint.

        Tavily expects:
        - POST to https://api.tavily.com/search
        - JSON body with "query" and "max_results"
        - No API key in the request (added by cassette layer)

        Args:
            query: the search query
            k: number of results to request

        Returns:
            HttpRequest ready to be hashed and sent
        """
        return HttpRequest(
            method="POST",
            url="https://api.tavily.com/search",
            headers={"Content-Type": "application/json"},
            body={
                "query": query,
                "max_results": k,
            },
        )

    def parse_response(self, response: dict) -> list[SearchResult]:
        """Parse Tavily's response into normalized SearchResults.

        Tavily returns:
        {
          "results": [
            {"url": "...", "title": "...", "content": "...", ...},
            ...
          ]
        }

        We extract url, title, and content (→ text), adding a 1-based rank.

        Args:
            response: Tavily's JSON response as a dict

        Returns:
            List of SearchResult

        Raises:
            KeyError: if response is missing expected fields
        """
        results = []
        for i, item in enumerate(response["results"], start=1):
            results.append(
                SearchResult(
                    rank=i,
                    url=item["url"],
                    title=item["title"],
                    text=item["content"],
                )
            )
        return results

    def add_auth_headers(self, headers: dict[str, str], api_key: str) -> dict[str, str]:
        """Add Tavily's API key to headers.

        Tavily uses: Authorization: Bearer <key>
        """
        return {**headers, "Authorization": f"Bearer {api_key}"}
