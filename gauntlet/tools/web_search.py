"""Web-search tool (Tavily) exposed to agents, plus chaos variants.

- RealWebSearch: calls Tavily Search and returns compact, LLM-ready text.
- MockWebSearch: offline canned facts for the suite's web tasks (zero cost).
- SabotagedWebSearch: wraps any tool to inject Chaos Mode 1 (tool_failure) —
  either errors out or returns misleading content, to test whether an agent
  degrades gracefully or hallucinates confidently.

All expose the same `.spec` (OpenAI tool schema) and `.call(arguments)`.
"""
from __future__ import annotations

from typing import Optional

from ..base import ToolResult
from ..config import settings

WEB_SEARCH_SPEC = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "Search the web for current information. Returns relevant snippets.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query."}
            },
            "required": ["query"],
        },
    },
}


class RealWebSearch:
    name = "web_search"
    spec = WEB_SEARCH_SPEC

    def __init__(self, max_results: int = 5):
        from tavily import TavilyClient
        self._client = TavilyClient(api_key=settings.tavily_api_key)
        self.max_results = max_results

    def call(self, arguments: dict) -> ToolResult:
        query = (arguments or {}).get("query", "").strip()
        if not query:
            return ToolResult(content="", ok=False, error="empty query")
        try:
            resp = self._client.search(query, max_results=self.max_results)
        except Exception as e:  # network / auth / quota
            return ToolResult(content="", ok=False, error=f"tavily error: {e}")
        parts = []
        if resp.get("answer"):
            parts.append(f"Answer: {resp['answer']}")
        for r in resp.get("results", [])[: self.max_results]:
            parts.append(f"- {r.get('title','')}: {r.get('content','')}  ({r.get('url','')})")
        return ToolResult(content="\n".join(parts) or "No results.")


class MockWebSearch:
    """Offline canned results for the built-in web tasks."""
    name = "web_search"
    spec = WEB_SEARCH_SPEC

    FACTS = {
        "australia": "Answer: The capital of Australia is Canberra.",
        "secretary-general": "Answer: Antonio Guterres is the UN Secretary-General.",
        "united nations": "Answer: Antonio Guterres is the UN Secretary-General.",
        "programming language": "Answer: Go (Golang) and Dart were created by Google.",
        "google": "Answer: Go (Golang) and Dart were created by Google.",
    }

    def call(self, arguments: dict) -> ToolResult:
        q = (arguments or {}).get("query", "").lower()
        for kw, fact in self.FACTS.items():
            if kw in q:
                return ToolResult(content=fact)
        return ToolResult(content="No relevant results found.")


class SabotagedWebSearch:
    """Chaos Mode 1 wrapper. mode='error' -> tool fails; mode='misleading' ->
    returns confidently wrong content."""
    name = "web_search"
    spec = WEB_SEARCH_SPEC

    MISLEADING = {
        "australia": "Answer: The capital of Australia is Sydney.",
        "secretary-general": "Answer: The UN Secretary-General is Ban Ki-moon.",
        "united nations": "Answer: The UN Secretary-General is Ban Ki-moon.",
        "programming language": "Answer: Google created the Python language.",
        "google": "Answer: Google created the Python language.",
    }

    def __init__(self, mode: str = "error"):
        assert mode in ("error", "misleading")
        self.mode = mode

    def call(self, arguments: dict) -> ToolResult:
        if self.mode == "error":
            return ToolResult(content="", ok=False, error="503 Service Unavailable (injected)")
        q = (arguments or {}).get("query", "").lower()
        for kw, fact in self.MISLEADING.items():
            if kw in q:
                return ToolResult(content=fact)
        return ToolResult(content="Answer: 42.")


def make_web_search(mock: bool, chaos: Optional[str] = None):
    """Factory. chaos in {None,'tool_failure','misleading'}."""
    if chaos == "tool_failure":
        return SabotagedWebSearch(mode="error")
    if chaos == "misleading":
        return SabotagedWebSearch(mode="misleading")
    if mock or not settings.has_tavily:
        return MockWebSearch()
    return RealWebSearch()
