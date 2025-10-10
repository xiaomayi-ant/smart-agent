"""
Document processing API routes.
Provides REST endpoints for PDF upload, search, and management.
"""
from datetime import datetime
from typing import List, Optional, Dict
import os
import tempfile
import shutil
import time
import uuid
from fastapi import APIRouter, UploadFile, File, HTTPException, Query, BackgroundTasks, Request
from pydantic import BaseModel
import asyncio
import urllib.parse
import urllib.request

from ..services.document_service import DocumentService

# Initialize router and service
router = APIRouter(prefix="/api/documents", tags=["documents"])
document_service = DocumentService()

# Simple in-memory file status store (use Redis in production)
file_status_store: Dict[str, Dict] = {}


# Request/Response models
class SearchRequest(BaseModel):
    query: str
    categories: Optional[List[str]] = None
    filename: Optional[str] = None
    limit: int = 5


class CategorySearchRequest(BaseModel):
    query: str
    category: str
    limit: int = 5


class RecommendationsRequest(BaseModel):
    filename: str
    limit: int = 3


class DeleteRequest(BaseModel):
    filename: str


# API Routes

# Removed /upload route (prefer /uploadByUrl)


@router.post("/uploadByUrl")
async def upload_pdf_by_url(
    background_tasks: BackgroundTasks,
    request: Request,
    url: str = Query(..., description="Public PDF URL (OSS URL)"),
    category: Optional[str] = Query(None, description="Optional category override"),
    filename: Optional[str] = Query(None, description="Optional filename, fallback to URL path"),
    fileId: Optional[str] = Query(None, description="Optional fileId to correlate with frontend"),
):
    """
    Download a PDF from URL and process it asynchronously (OSS -> backend).
    Returns the same shape as /api/documents/upload?mode=async.
    """
    try:
        # Validate URL
        parsed = urllib.parse.urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            raise HTTPException(status_code=400, detail="Invalid url")

        # Infer filename
        inferred_name = filename or (parsed.path.rsplit("/", 1)[-1] if parsed.path else "")
        if not inferred_name:
            inferred_name = f"document_{int(time.time())}.pdf"

        # Download bytes in background thread
        def _download() -> bytes:
            with urllib.request.urlopen(url, timeout=20) as resp:
                content_type = resp.headers.get("Content-Type", "")
                data = resp.read()
                # Enforce PDF by header or file suffix
                if ("application/pdf" not in content_type) and (not inferred_name.lower().endswith(".pdf")):
                    raise ValueError(f"Unsupported content type: {content_type or 'unknown'}")
                return data

        loop = asyncio.get_event_loop()
        file_bytes = await loop.run_in_executor(None, _download)

        # Allocate fileId and persist to temp path
        file_id = fileId or f"file_{int(time.time())}_{uuid.uuid4().hex[:8]}"
        tmp_dir = tempfile.mkdtemp(prefix="uploads_")
        safe_name = inferred_name if inferred_name.lower().endswith(".pdf") else (inferred_name + ".pdf")
        tmp_path = os.path.join(tmp_dir, safe_name)
        with open(tmp_path, "wb") as out_f:
            out_f.write(file_bytes)

        # Store file status
        file_status_store[file_id] = {
            "status": "processing",
            "filename": safe_name,
            "category": category,
            "timestamp": datetime.now().isoformat(),
            "user_id": getattr(request.state, "user_id", None),
            "source": "url",
            "url": url,
        }

        # Start background processing with the tmp file path
        background_tasks.add_task(
            process_pdf_async,
            file_id,
            tmp_path,
            category,
            getattr(request.state, "user_id", None),
        )

        # Return pointer immediately (aligned with /upload?mode=async)
        return {
            "fileId": file_id,
            "url": f"/api/documents/{file_id}",
            "name": safe_name,
            "mime": "application/pdf",
            "size": len(file_bytes),
            "status": "processing",
            "timestamp": datetime.now().isoformat(),
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"uploadByUrl error: {str(e)}")


async def process_pdf_async(file_id: str, file_path: str, category: Optional[str], user_id: Optional[str]):
    """Background async processing of PDF file from a persisted temp path."""
    try:
        # Reopen the file from disk to build an UploadFile-like object
        from starlette.datastructures import UploadFile as StarletteUploadFile
        result = None
        with open(file_path, "rb") as f:
            uf = StarletteUploadFile(filename=os.path.basename(file_path), file=f)  # type: ignore
            result = await document_service.upload_and_process_pdf(uf, category, user_id)
        
        if result.get("success"):
            file_status_store[file_id].update({
                "status": "ready",
                "result": result,
                "processed_at": datetime.now().isoformat()
            })
        else:
            file_status_store[file_id].update({
                "status": "failed",
                "error": result.get("error", "Processing failed"),
                "failed_at": datetime.now().isoformat()
            })
    except Exception as e:
        file_status_store[file_id].update({
            "status": "failed", 
            "error": str(e),
            "failed_at": datetime.now().isoformat()
        })
    finally:
        # Cleanup temp file directory
        try:
            shutil.rmtree(os.path.dirname(file_path), ignore_errors=True)
        except Exception:
            pass


@router.get("/status")
async def get_file_status(request: Request, fileId: str = Query(..., description="File ID to check status")):
    """
    Query file processing status.
    
    - **fileId**: File ID returned from async upload
    """
    if fileId not in file_status_store:
        raise HTTPException(status_code=404, detail="File not found")
    
    status_info = file_status_store[fileId]
    req_uid = getattr(request.state, "user_id", None)
    if status_info.get("user_id") and status_info.get("user_id") != req_uid:
        raise HTTPException(status_code=404, detail="File not found")
    response = {
        "fileId": fileId,
        "status": status_info["status"],
        "filename": status_info.get("filename"),
        "timestamp": status_info.get("timestamp")
    }
    
    # Include processing result if ready
    if status_info["status"] == "ready" and "result" in status_info:
        response["result"] = status_info["result"]
    
    # Include error details if failed
    if status_info["status"] == "failed" and "error" in status_info:
        response["error"] = status_info["error"]
    
    return response


# @router.post("/search")
# async def search_documents(request: SearchRequest):
#     """
#     Search documents using semantic similarity.
#     
#     - **query**: Search query text
#     - **categories**: Optional list of categories to search within
#     - **filename**: Optional specific filename to search
#     - **limit**: Maximum number of results (default: 5)
#     """
#     try:
#         result = await document_service.search_documents(
#             query=request.query,
#             categories=request.categories,
#             filename=request.filename,
#             limit=request.limit
#         )
#         
#         if result.get("success"):
#             return {
#                 "success": True,
#                 "query": request.query,
#                 "total_found": result["total_found"],
#                 "results": result["results"],
#                 "searched_partitions": result.get("searched_partitions", []),
#                 "statistics": result.get("statistics", {})
#             }
#         else:
#             raise HTTPException(status_code=400, detail=result.get("error", "Search failed"))
            
    # except HTTPException:
    #     raise
    # except Exception as e:
    #     raise HTTPException(status_code=500, detail=f"Search error: {str(e)}")


# @router.post("/search/category")
# async def search_by_category(request: CategorySearchRequest):
#     """
#     Search documents within a specific category.
#     
#     - **query**: Search query text
#     - **category**: Target category
#     - **limit**: Maximum number of results
#     """
#     try:
#         result = await document_service.search_documents(
#             query=request.query,
#             categories=[request.category],
#             limit=request.limit
#         )
#         
#         if result.get("success"):
#             return {
#                 "success": True,
#                 "query": request.query,
#                 "category": request.category,
#                 "total_found": result["total_found"],
#                 "results": result["results"]
#             }
#         else:
#             raise HTTPException(status_code=400, detail=result.get("error", "Category search failed"))
            
    # except HTTPException:
    #     raise
    # except Exception as e:
    #     raise HTTPException(status_code=500, detail=f"Category search error: {str(e)}")


# @router.get("/categories")
# async def get_categories():
#     """
#     Get information about available document categories.
#     
#     Returns category names, descriptions, and document counts.
#     """
#     try:
#         result = await document_service.get_categories_info()
#         
#         if result.get("success"):
#             return {
#                 "success": True,
#                 "categories": result["categories"],
#                 "total_categories": result["total_categories"]
#             }
#         else:
#             raise HTTPException(status_code=500, detail=result.get("error", "Failed to get categories"))
            
    # except HTTPException:
    #     raise
    # except Exception as e:
    #     raise HTTPException(status_code=500, detail=f"Categories error: {str(e)}")


# @router.post("/recommendations")
# async def get_recommendations(request: RecommendationsRequest):
#     """
#     Get document recommendations based on similarity to a reference document.
#     
#     - **filename**: Reference document filename
#     - **limit**: Number of recommendations (default: 3)
#     """
#     try:
#         result = await document_service.get_document_recommendations(
#             filename=request.filename,
#             limit=request.limit
#         )
#         
#         if result.get("success"):
#             return {
#                 "success": True,
#                 "reference_filename": result["reference_filename"],
#                 "recommendations": result["recommendations"],
#                 "total_recommendations": result["total_recommendations"]
#             }
#         else:
#             raise HTTPException(status_code=404, detail=result.get("error", "Recommendations failed"))
            
    # except HTTPException:
    #     raise
    #     
    # except Exception as e:
    #     raise HTTPException(status_code=500, detail=f"Recommendations error: {str(e)}")


# @router.delete("/delete")
# async def delete_document(request: DeleteRequest):
#     """
#     Delete a document and all its chunks.
#     
#     - **filename**: Filename of the document to delete
#     """
#     try:
#         result = await document_service.delete_document(request.filename)
#         
#         if result.get("success"):
#             return {
#                 "success": True,
#                 "filename": result["filename"],
#                 "deleted_chunks": result["deleted_chunks"],
#                 "message": result.get("message", "Document deleted successfully")
#             }
#         else:
#             raise HTTPException(status_code=404, detail=result.get("error", "Delete failed"))
            
    # except HTTPException:
    #     raise
    # except Exception as e:
    #     raise HTTPException(status_code=500, detail=f"Delete error: {str(e)}")


# @router.get("/stats")
# async def get_system_stats():
#     """
#     Get system statistics and health information.
#     
#     Returns processing stats, search engine health, and partition information.
#     """
#     try:
#         result = await document_service.get_system_stats()
#         
#         if result.get("success"):
#             return {
#                 "success": True,
#                 "timestamp": datetime.now().isoformat(),
#                 "processing_stats": result["processing_stats"],
#                 "search_health": result["search_health"]
#             }
#         else:
#             raise HTTPException(status_code=500, detail=result.get("error", "Stats failed"))
            
    # except HTTPException:
    #     raise
    # except Exception as e:
    #     raise HTTPException(status_code=500, detail=f"Stats error: {str(e)}")


@router.get("/health")
async def health_check():
    """
    Simple health check for document processing system.
    """
    try:
        # Quick health check
        result = await document_service.get_system_stats()
        
        return {
            "status": "healthy" if result.get("success") else "degraded",
            "timestamp": datetime.now().isoformat(),
            "message": "Document processing system operational"
        }
        
    except Exception as e:
        return {
            "status": "error",
            "timestamp": datetime.now().isoformat(),
            "message": f"Health check failed: {str(e)}"
        }
