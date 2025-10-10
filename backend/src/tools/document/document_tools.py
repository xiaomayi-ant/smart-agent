"""
LangChain tools for document processing and search.
These tools integrate PDF processing capabilities into the LangGraph workflow.
"""
from typing import Dict, Any, List, Optional
from langchain.tools import tool

from .search_engine import DocumentSearchEngine
from .processor import PDFProcessor
from .classifier import DOCUMENT_CATEGORIES

# Global instances
_search_engine = None
_pdf_processor = None


def get_search_engine() -> DocumentSearchEngine:
    """Get or create global search engine instance."""
    global _search_engine
    if _search_engine is None:
        _search_engine = DocumentSearchEngine()
    return _search_engine


def get_pdf_processor() -> PDFProcessor:
    """Get or create global PDF processor instance."""
    global _pdf_processor
    if _pdf_processor is None:
        _pdf_processor = PDFProcessor()
    return _pdf_processor


@tool
async def search_documents_tool(
    query: str,
    categories: Optional[str] = None,
    filename: Optional[str] = None,
    limit: int = 5,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Search through uploaded PDF documents using semantic similarity.
    
    Args:
        query: Search query text to find relevant documents
        categories: Comma-separated list of categories to search (finance,ai,blockchain,robotics,technology,general)
        filename: Specific filename to search within (optional)
        limit: Maximum number of results to return (default: 5)
    
    Returns:
        Search results with document content, metadata, and similarity scores
    """
    try:
        search_engine = get_search_engine()
        
        # Parse categories
        category_list = None
        if categories:
            category_list = [cat.strip().lower() for cat in categories.split(",")]
            # Validate categories
            valid_categories = [cat for cat in category_list if cat in DOCUMENT_CATEGORIES]
            if valid_categories:
                category_list = valid_categories
            else:
                return {
                    "success": False,
                    "error": f"Invalid categories: {categories}. Valid categories: {', '.join(DOCUMENT_CATEGORIES.keys())}",
                    "results": []
                }
        
        # Perform search（若无 user_id 则不做用户级过滤）
        results = await search_engine.search_documents(
            query=query,
            categories=category_list,
            filename=filename,
            limit=limit,
            user_id=user_id,
        )
        
        if results.get("success"):
            return {
                "success": True,
                "query": query,
                "results": results["results"],
                "total_found": results["total_found"],
                "searched_categories": category_list or "all",
                "message": f"Found {results['total_found']} relevant documents"
            }
        else:
            return {
                "success": False,
                "error": results.get("error", "Unknown search error"),
                "results": []
            }
    
    except Exception as e:
        return {
            "success": False,
            "error": f"Search tool error: {str(e)}",
            "results": []
        }


@tool
async def search_documents_by_category_tool(
    query: str,
    category: str,
    limit: int = 5,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Search documents within a specific category.
    
    Args:
        query: Search query text
        category: Document category (finance, ai, blockchain, robotics, technology, general)
        limit: Maximum number of results
    
    Returns:
        Category-specific search results
    """
    try:
        if category.lower() not in DOCUMENT_CATEGORIES:
            return {
                "success": False,
                "error": f"Invalid category: {category}. Valid categories: {', '.join(DOCUMENT_CATEGORIES.keys())}",
                "results": []
            }
        
        search_engine = get_search_engine()
        if not user_id:
            return {"success": False, "error": "missing user_id context", "results": []}

        results = await search_engine.search_by_category(
            query=query,
            category=category.lower(),
            limit=limit,
            user_id=user_id,
        )
        
        if results.get("success"):
            return {
                "success": True,
                "query": query,
                "category": category,
                "results": results["results"],
                "total_found": len(results["results"]),
                "message": f"Found {len(results['results'])} documents in {category} category"
            }
        else:
            return results
    
    except Exception as e:
        return {
            "success": False,
            "error": f"Category search error: {str(e)}",
            "results": []
        }


@tool
async def list_document_categories_tool() -> Dict[str, Any]:
    """
    List all available document categories with statistics.
    
    Returns:
        Information about document categories and their contents
    """
    try:
        search_engine = get_search_engine()
        
        # Get category information
        categories_info = {}
        for category, info in DOCUMENT_CATEGORIES.items():
            categories_info[category] = {
                "name": info["name"],
                "description": info["description"],
                "partition": info["partition"]
            }
        
        # Get partition statistics if available
        try:
            if search_engine.partition_manager:
                partition_stats = await search_engine.partition_manager.get_partition_stats()
                
                # Add document counts to category info
                for category, info in categories_info.items():
                    partition_name = info["partition"]
                    partition_data = partition_stats.get("partitions", {}).get(partition_name, {})
                    info["document_count"] = partition_data.get("row_count", 0)
            
        except Exception as e:
            # Continue without stats
            pass
        
        return {
            "success": True,
            "categories": categories_info,
            "total_categories": len(categories_info),
            "message": "Document categories retrieved successfully"
        }
    
    except Exception as e:
        return {
            "success": False,
            "error": f"Error listing categories: {str(e)}",
            "categories": {}
        }


@tool
async def get_document_recommendations_tool(
    filename: str,
    limit: int = 3
) -> Dict[str, Any]:
    """
    Get document recommendations based on similarity to a reference document.
    
    Args:
        filename: Reference document filename
        limit: Number of recommendations to return
    
    Returns:
        Recommended similar documents
    """
    try:
        search_engine = get_search_engine()
        results = await search_engine.get_document_recommendations(
            filename=filename,
            limit=limit
        )
        
        if results.get("success"):
            return {
                "success": True,
                "reference_filename": filename,
                "recommendations": results["recommendations"],
                "total_recommendations": results["total_recommendations"],
                "message": f"Found {results['total_recommendations']} similar documents"
            }
        else:
            return results
    
    except Exception as e:
        return {
            "success": False,
            "error": f"Recommendations error: {str(e)}",
            "recommendations": []
        }


@tool
async def upload_pdf_tool(
    file_content_base64: str,
    filename: str,
    category: Optional[str] = None
) -> Dict[str, Any]:
    """
    Upload and process a PDF document (Base64 encoded).
    Note: This tool is primarily for API use. File uploads through web interface are preferred.
    
    Args:
        file_content_base64: Base64 encoded PDF file content
        filename: Original filename of the PDF
        category: Optional category override (finance, ai, blockchain, robotics, technology, general)
    
    Returns:
        Processing result with classification and storage information
    """
    try:
        import base64
        
        # Decode base64 content
        try:
            file_content = base64.b64decode(file_content_base64)
        except Exception as e:
            return {
                "success": False,
                "error": f"Invalid base64 content: {str(e)}",
                "filename": filename
            }
        
        # Validate category if provided
        if category and category.lower() not in DOCUMENT_CATEGORIES:
            return {
                "success": False,
                "error": f"Invalid category: {category}. Valid categories: {', '.join(DOCUMENT_CATEGORIES.keys())}",
                "filename": filename
            }
        
        # Process PDF
        processor = get_pdf_processor()
        result = await processor.process_pdf_content(
            file_content=file_content,
            filename=filename,
            user_category=category.lower() if category else None
        )
        
        if result.get("success"):
            return {
                "success": True,
                "filename": result["filename"],
                "category": result["category"],
                "category_name": result["category_name"],
                "chunks_processed": result["chunks_processed"],
                "confidence": result["confidence"],
                "message": f"Successfully processed {filename} into {result['category']} category"
            }
        else:
            return result
    
    except Exception as e:
        return {
            "success": False,
            "error": f"Upload processing error: {str(e)}",
            "filename": filename
        }


@tool
async def get_document_processing_stats_tool() -> Dict[str, Any]:
    """
    Get statistics about document processing and storage.
    
    Returns:
        Processing statistics and system health information
    """
    try:
        processor = get_pdf_processor()
        search_engine = get_search_engine()
        
        # Get processing stats
        processing_stats = await processor.get_processing_stats()
        
        # Get search engine health
        search_health = await search_engine.get_search_health()
        
        return {
            "success": True,
            "processing_stats": processing_stats,
            "search_health": search_health,
            "message": "System statistics retrieved successfully"
        }
    
    except Exception as e:
        return {
            "success": False,
            "error": f"Stats error: {str(e)}"
        }


@tool
async def delete_document_tool(filename: str) -> Dict[str, Any]:
    """
    Delete a document and all its chunks from the system.
    
    Args:
        filename: Filename of the document to delete
    
    Returns:
        Deletion result
    """
    try:
        processor = get_pdf_processor()
        result = await processor.delete_document_by_filename(filename)
        
        if result.get("success"):
            return {
                "success": True,
                "filename": filename,
                "deleted_chunks": result["deleted_chunks"],
                "message": f"Successfully deleted {filename} ({result['deleted_chunks']} chunks)"
            }
        else:
            return result
    
    except Exception as e:
        return {
            "success": False,
            "error": f"Delete error: {str(e)}",
            "filename": filename
        }
