"""
Thin wrapper for Tavily web search API (prototype).
"""
from typing import List, Dict, Any
import time
import httpx

from ...core.config import settings
from langchain.tools import tool


class TavilyClient:
    def __init__(self, api_key: str | None = None, timeout_s: float = 8.0):
        self.api_key = api_key or settings.tavily_api_key
        self.timeout_s = timeout_s
        self.base_url = "https://api.tavily.com"

    async def search(self, query: str, max_results: int = 5) -> Dict[str, Any]:
        if not self.api_key:
            return {"success": False, "error": "TAVILY_API_KEY not configured"}

        payload = {
            "api_key": self.api_key,
            "query": query,
            "search_depth": "basic",
            "max_results": max(1, min(max_results, 10)),
        }

        started = time.time()
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                resp = await client.post(f"{self.base_url}/search", json=payload)
                took_ms = int((time.time() - started) * 1000)
                if resp.status_code != 200:
                    return {
                        "success": False,
                        "used_provider": "tavily",
                        "error": f"HTTP {resp.status_code}",
                        "took_ms": took_ms,
                    }
                data = resp.json() or {}
                # Normalize results
                items = []
                for r in data.get("results", [])[:payload["max_results"]]:
                    items.append({
                        "title": r.get("title", ""),
                        "url": r.get("url", ""),
                        "snippet": r.get("content", "")[:500],
                    })
                return {
                    "success": True,
                    "used_provider": "tavily",
                    "results": items,
                    "took_ms": took_ms,
                }
        except Exception as e:
            return {"success": False, "used_provider": "tavily", "error": str(e)}


async def tavily_search(query: str, max_results: int = 5) -> Dict[str, Any]:
    client = TavilyClient()
    return await client.search(query=query, max_results=max_results)



@tool
async def tavily_search_tool(query: str, max_results: int = 5) -> Dict[str, Any]:
    """
    Perform a web search via Tavily and return normalized results.
    Args:
        query: Search query string
        max_results: Maximum number of results to return (1-10)
    Returns:
        Dict with fields: success(bool), results(list[{title,url,snippet}]), used_provider(str), took_ms(int), error(str|optional)
    """
    try:
        result = await tavily_search(query=query, max_results=max_results)
        return result
    except Exception as e:
        return {"success": False, "used_provider": "tavily", "error": str(e)}

