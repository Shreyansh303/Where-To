"""SerpApi Google web-search client — the source for the city planning brief.

Unlike the flights/hotels clients (which return structured entities we ground
on), this returns raw travel-guide *text* (organic snippets, answer boxes,
knowledge-graph blurbs) that a downstream LLM extraction pass distills into
per-attraction durations and prices. The text is a research aid, never copied
verbatim into the plan as fact — see `app/research/brief.py`.
"""

from typing import Any

from .base import BaseClient

SERPAPI_URL = "https://serpapi.com/search.json"


def _snippets(raw: dict[str, Any]) -> list[str]:
    """Flatten the useful text out of a SerpApi Google result."""
    out: list[str] = []
    answer = raw.get("answer_box") or {}
    for key in ("answer", "snippet", "title"):
        if answer.get(key):
            out.append(str(answer[key]))
    for item in answer.get("list") or []:
        out.append(str(item))
    kg = raw.get("knowledge_graph") or {}
    if kg.get("description"):
        out.append(str(kg["description"]))
    for r in raw.get("organic_results") or []:
        line = " ".join(str(r[k]) for k in ("title", "snippet") if r.get(k))
        if r.get("link"):
            line = f"{line} (source: {r['link']})"
        if line:
            out.append(line)
    return out


class SearchClient(BaseClient):
    service = "research"

    def __init__(self, api_key: str, **kwargs):
        super().__init__(**kwargs)
        self.api_key = api_key

    def search_text(self, query: str, num: int = 8, no_cache: bool = False) -> list[str]:
        """Return a list of text snippets for a web query (cache-first)."""
        cache_params = {"engine": "google", "q": query, "num": num, "hl": "en"}

        def fetch() -> Any:
            request_params = dict(cache_params)
            request_params["api_key"] = self.api_key
            if no_cache:
                request_params["no_cache"] = "true"
            return self._request_json("GET", SERPAPI_URL, params=request_params)

        raw = self._cached_json(cache_params, fetch, no_cache=no_cache)
        return _snippets(raw)
