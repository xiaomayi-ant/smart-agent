from typing import Dict, Any, List, Optional
from langchain.tools import tool
from .vector_search import hybrid_milvus_search


@tool
async def hybrid_milvus_search_tool(query: Optional[str] = None, publish_time: Optional[str] = None, limit: int = 3) -> Dict[str, Any]:
    """Search for financial news and documents using hybrid vector and metadata search"""
    try:
        results = await hybrid_milvus_search(query, publish_time, limit)
        return {
            "success": True,
            "data": results,
            "count": len(results),
            "message": f"Successfully found {len(results)} relevant documents"
        }
    except Exception as e:
        return {"success": False, "data": None, "message": str(e)} 