"""Exa adapter: translates between Exa's API and our common interface.

Exa's search API has different field names than Tavily:
- "numResults" instead of "max_results"
- "text" instead of "content" (and must be explicitly requested)

This adapter normalizes Exa's response into our common SearchResult shape,
so the scoring layer doesn't need to know which vendor it came from.
"""

from searchdrift.vendors.types import HttpRequest, SearchResult


class ExaAdapter:
    """Adapter for Exa's search API (api.exa.ai).

    Exa's response format:
    {
      "results": [
        {
          "url": "https://example.com",
          "title": "Example Title",
          "text": "Snippet text here...",  // only if contents requested
          ...
        },
        ...
      ]
    }

    Note: Exa requires explicitly requesting "contents" in the request body,
    otherwise the "text" field is missing from results.
    """

    @property
    def vendor_id(self) -> str:
        return "exa"

    def build_request(self, query: str, k: int) -> HttpRequest:
        """Build the HTTP request for Exa's search endpoint.

        Exa expects:
        - POST to https://api.exa.ai/search
        - JSON body with "query" and "numResults"
        - "contents": {"text": true} to get text snippets

        Args:
            query: the search query
            k: number of results to request

        Returns:
            HttpRequest ready to be hashed and sent
        """
        return HttpRequest(
            method="POST",
            url="https://api.exa.ai/search",
            headers={"Content-Type": "application/json"},
            body={
                "query": query,
                "numResults": k,
                "contents": {"text": True},  # Request text snippets
            },
        )

    def parse_response(self, response: dict) -> list[SearchResult]:
        """Parse Exa's response into normalized SearchResults.

        Exa returns:
        {
          "results": [
            {"url": "...", "title": "...", "text": "...", ...},
            ...
          ]
        }

        We extract url, title, and text, adding a 1-based rank.

        Args:
            response: Exa's JSON response as a dict

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
                    text=item["text"],
                )
            )
        return results

    def add_auth_headers(self, headers: dict[str, str], api_key: str) -> dict[str, str]:
        """Add Exa's API key to headers.

        Exa uses: x-api-key: <key>
        """
        return {**headers, "x-api-key": api_key}
