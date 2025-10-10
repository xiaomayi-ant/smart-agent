"""
Document service layer for handling PDF uploads and management.
Provides high-level API for document processing operations.
"""
from typing import Dict, Any, List, Optional
from fastapi import UploadFile
import tempfile
import os

from ..tools.document.processor import PDFProcessor
from ..tools.document.search_engine import DocumentSearchEngine
from ..tools.document.classifier import DOCUMENT_CATEGORIES


class DocumentService:
    """High-level service for document operations."""
    
    def __init__(self):
        self.pdf_processor = PDFProcessor()
        self.search_engine = DocumentSearchEngine()
    
    async def upload_and_process_pdf(self, 
                                   file: UploadFile,
                                   user_category: Optional[str] = None,
                                   user_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Upload and process a PDF file.
        
        Args:
            file: Uploaded PDF file
            user_category: Optional user-specified category
            
        Returns:
            Processing result
        """
        try:
            # Validate file type
            if not file.filename.lower().endswith('.pdf'):
                return {
                    "success": False,
                    "error": "Only PDF files are supported",
                    "filename": file.filename
                }
            
            # Validate category if provided
            if user_category and user_category.lower() not in DOCUMENT_CATEGORIES:
                return {
                    "success": False,
                    "error": f"Invalid category: {user_category}. Valid categories: {', '.join(DOCUMENT_CATEGORIES.keys())}",
                    "filename": file.filename
                }
            
            # Read file content
            file_content = await file.read()
            
            # Process PDF
            result = await self.pdf_processor.process_pdf_content(
                file_content=file_content,
                filename=file.filename,
                user_category=user_category.lower() if user_category else None,
                user_id=user_id,
            )
            
            return result
            
        except Exception as e:
            return {
                "success": False,
                "error": f"Upload processing error: {str(e)}",
                "filename": file.filename if file else "unknown"
            }
    
    async def search_documents(self,
                             query: str,
                             categories: Optional[List[str]] = None,
                             filename: Optional[str] = None,
                             limit: int = 5) -> Dict[str, Any]:
        """
        Search documents with flexible filtering.
        
        Args:
            query: Search query
            categories: List of categories to search
            filename: Specific filename filter
            limit: Maximum results
            
        Returns:
            Search results
        """
        try:
            return await self.search_engine.search_documents(
                query=query,
                categories=categories,
                filename=filename,
                limit=limit
            )
        except Exception as e:
            return {
                "success": False,
                "error": f"Search error: {str(e)}",
                "results": []
            }
    
    async def get_categories_info(self) -> Dict[str, Any]:
        """Get information about available document categories."""
        try:
            categories_info = {}
            for category, info in DOCUMENT_CATEGORIES.items():
                categories_info[category] = {
                    "name": info["name"],
                    "description": info["description"],
                    "partition": info["partition"]
                }
            
            # Try to get partition statistics
            try:
                if self.search_engine.partition_manager:
                    partition_stats = await self.search_engine.partition_manager.get_partition_stats()
                    
                    for category, info in categories_info.items():
                        partition_name = info["partition"]
                        partition_data = partition_stats.get("partitions", {}).get(partition_name, {})
                        info["document_count"] = partition_data.get("row_count", 0)
            except:
                # Continue without stats if there's an error
                pass
            
            return {
                "success": True,
                "categories": categories_info,
                "total_categories": len(categories_info)
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": f"Error getting categories: {str(e)}",
                "categories": {}
            }
    
    async def delete_document(self, filename: str) -> Dict[str, Any]:
        """Delete a document by filename."""
        try:
            return await self.pdf_processor.delete_document_by_filename(filename)
        except Exception as e:
            return {
                "success": False,
                "error": f"Delete error: {str(e)}",
                "filename": filename
            }
    
    async def get_system_stats(self) -> Dict[str, Any]:
        """Get system statistics and health information."""
        try:
            processing_stats = await self.pdf_processor.get_processing_stats()
            search_health = await self.search_engine.get_search_health()
            
            return {
                "success": True,
                "processing_stats": processing_stats,
                "search_health": search_health,
                "timestamp": None  # Will be set by API
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": f"Stats error: {str(e)}"
            }
    
    async def get_document_recommendations(self, filename: str, limit: int = 3) -> Dict[str, Any]:
        """Get document recommendations based on similarity."""
        try:
            return await self.search_engine.get_document_recommendations(
                filename=filename,
                limit=limit
            )
        except Exception as e:
            return {
                "success": False,
                "error": f"Recommendations error: {str(e)}",
                "recommendations": []
            }
