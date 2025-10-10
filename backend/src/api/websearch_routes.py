"""
Web search (Tavily) API routes - minimal prototype.
"""
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..tools.web.tavily import tavily_search


router = APIRouter(prefix="/api/websearch", tags=["websearch"])


class WebSearchRequest(BaseModel):
    query: str
    max_results: Optional[int] = 5


@router.post("/search")
async def websearch_search(req: WebSearchRequest):
    """Perform a web search using Tavily and return normalized results."""
    try:
        result = await tavily_search(req.query, req.max_results or 5)
        if not result.get("success"):
            raise HTTPException(status_code=400, detail=result.get("error", "Search failed"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Web search error: {e}")


