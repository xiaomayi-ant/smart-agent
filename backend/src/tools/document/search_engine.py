"""
Document search engine with cross-partition capabilities.
Provides intelligent search across document categories with flexible filtering.
"""
import asyncio
from typing import List, Dict, Any, Optional
from langchain_openai import OpenAIEmbeddings
from pymilvus import MilvusClient

from .partition_manager import PartitionManager
from .classifier import DOCUMENT_CATEGORIES
from ...core.config import get_milvus_config, settings


class DocumentSearchEngine:
    """
    Advanced document search engine supporting:
    - Cross-partition search
    - Category-specific search  
    - Metadata filtering
    - Intelligent result ranking
    """
    
    def __init__(self):
        self.milvus_config = get_milvus_config()
        self.client = None
        self.embeddings = None
        self.partition_manager = None
        self.categories = DOCUMENT_CATEGORIES
        
        self._init_connections()
    
    def _init_connections(self):
        """Initialize connections to Milvus and OpenAI."""
        try:
            # Initialize Milvus client
            if self.milvus_config.get("address"):
                self.client = MilvusClient(
                    uri=f"http://{self.milvus_config['address']}"
                )
                self.partition_manager = PartitionManager(self.client)
            
            # Initialize OpenAI embeddings
            # Prefer embeddings-specific credentials if provided
            effective_api_key = settings.openai_embed_api_key or settings.openai_api_key
            effective_base_url = settings.openai_embed_base_url or settings.openai_base_url
            if effective_api_key:
                self.embeddings = OpenAIEmbeddings(
                    openai_api_key=effective_api_key,
                    base_url=effective_base_url,
                    model=(settings.openai_embed_model or "text-embedding-ada-002")
                )
                
        except Exception as e:
            print(f"[DocumentSearchEngine] Initialization error: {e}")
            self.client = None
            self.embeddings = None
            self.partition_manager = None
    
    async def search_documents(self,
                              query: str,
                              categories: Optional[List[str]] = None,
                              filename: Optional[str] = None,
                              limit: int = 5,
                              min_score: float = 0.0,
                              user_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Search documents across partitions with flexible filtering.
        
        Args:
            query: Search query text
            categories: List of categories to search (None = all categories)
            filename: Specific filename to search within
            limit: Maximum number of results
            min_score: Minimum similarity score threshold
            
        Returns:
            Search results with metadata and statistics
        """
        # Fail-closed: 缺少用户上下文则直接返回空结果，避免跨用户数据泄露
        if not user_id or str(user_id).strip() == "":
            target_partitions = self._get_target_partitions(categories)
            return {
                "success": True,
                "query": query,
                "results": [],
                "total_found": 0,
                "searched_partitions": target_partitions,
                "statistics": {"reason": "missing_user_context"}
            }

        if not self._check_prerequisites():
            return {
                "success": False,
                "error": "Search engine not properly initialized",
                "results": []
            }
        
        try:
            # Generate query embedding
            query_vector = await self._generate_query_embedding(query)
            if not query_vector:
                return {
                    "success": False,
                    "error": "Failed to generate query embedding",
                    "results": []
                }
            
            # Determine target partitions
            target_partitions = self._get_target_partitions(categories)
            if not target_partitions:
                return {
                    "success": False,
                    "error": "No valid partitions to search",
                    "results": []
                }
            
            # Dual-search plan (short-term):
            # 1) Private search with strict equality expr
            # 2) Public search without expr, restricted to public partitions
            #    Then merge locally with null-compatible visibility

            private_expr = f'$meta["metadata"]["user_id"] == "{user_id}"'
            public_partitions = list(self.partition_manager.partitions)

            # TRACE：打印检索摘要（不打印向量内容）
            # (trace_events 调试日志已精简)

            # 确保集合与分区就绪（若未初始化）
            if self.partition_manager:
                try:
                    await self.partition_manager.ensure_collection_and_partitions()
                except Exception:
                    pass

            # Fire two searches in parallel
            private_coro = self.partition_manager.search_partitions(
                query_vector=query_vector,
                partitions=target_partitions,
                limit=limit * 2,
                filter_expr=private_expr,
            )
            public_coro = self.partition_manager.search_partitions(
                query_vector=query_vector,
                partitions=public_partitions,
                limit=limit * 3,
                filter_expr=None,
            )

            raw_private, raw_public = await asyncio.gather(private_coro, public_coro)
            raw_results = (raw_private or []) + (raw_public or [])
            
            # Process and rank results
            processed_results = self._process_and_rank_results(
                raw_results, query, min_score, max(limit * 3, 20)
            )

            # Enforce per-user visibility with null compatibility
            # null值兼容：user_id为null的数据视为公共数据，所有用户都可访问
            if user_id is not None:
                # Keep private (owner) or public (null) only
                filtered = []
                seen = set()
                for r in processed_results:
                    meta = r.get("metadata", {}) or {}
                    uid = meta.get("user_id")
                    if uid is not None and str(uid) != str(user_id):
                        continue
                    # Deduplicate by id if present, else by (filename,page,text-hash)
                    key = r.get("id") or (
                        meta.get("filename"),
                        meta.get("page"),
                        (r.get("text", "")[:100] if isinstance(r.get("text"), str) else "")
                    )
                    if key in seen:
                        continue
                    seen.add(key)
                    filtered.append(r)
                # Re-rank and cut to limit
                filtered.sort(key=lambda x: x.get("score", 0.0), reverse=True)
                processed_results = filtered[:limit]

            # Local post-filter by filename for stability/compatibility
            if filename:
                filtered = []
                for r in processed_results:
                    meta = r.get("metadata", {})
                    if meta.get("filename") == filename:
                        filtered.append(r)
                processed_results = filtered
            
            # Compile search statistics
            stats = self._compile_search_stats(processed_results, target_partitions, query)
            
            return {
                "success": True,
                "query": query,
                "results": processed_results,
                "total_found": len(processed_results),
                "searched_partitions": target_partitions,
                "statistics": stats
            }
            
        except Exception as e:
            print(f"[DocumentSearchEngine] Search error: {e}")
            return {
                "success": False,
                "error": str(e),
                "results": []
            }
    
    async def search_by_category(self,
                                query: str,
                                category: str,
                                limit: int = 5,
                                user_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Search within a specific document category.
        
        Args:
            query: Search query
            category: Target category
            limit: Maximum results
            
        Returns:
            Category-specific search results
        """
        # Fail-closed: 缺少用户上下文则直接返回空
        if not user_id or str(user_id).strip() == "":
            return {"success": True, "results": [], "total_found": 0, "query": query, "category": category, "statistics": {"reason": "missing_user_context"}}

        if category not in self.categories:
            return {
                "success": False,
                "error": f"Invalid category: {category}",
                "results": []
            }
        
        return await self.search_documents(
            query=query,
            categories=[category],
            limit=limit,
            user_id=user_id
        )
    
    async def search_similar_documents(self,
                                     reference_text: str,
                                     exclude_filename: Optional[str] = None,
                                     limit: int = 5,
                                     user_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Find documents similar to reference text.
        
        Args:
            reference_text: Reference text to find similar documents
            exclude_filename: Filename to exclude from results
            limit: Maximum results
            
        Returns:
            Similar documents search results
        """
        # Fail-closed: 缺少用户上下文则直接返回空
        if not user_id or str(user_id).strip() == "":
            return {"success": True, "results": [], "total_found": 0, "reference_text": reference_text[:200] if isinstance(reference_text, str) else "", "statistics": {"reason": "missing_user_context"}}
        # Build exclusion filter
        filter_expr = None
        if exclude_filename:
            filter_expr = f'metadata["filename"] != "{exclude_filename}"'
        
        try:
            query_vector = await self._generate_query_embedding(reference_text)
            if not query_vector:
                return {
                    "success": False,
                    "error": "Failed to generate reference embedding",
                    "results": []
                }
            
            raw_results = await self.partition_manager.search_partitions(
                query_vector=query_vector,
                partitions=None,  # Search all partitions
                limit=limit,
                filter_expr=filter_expr
            )
            
            processed_results = self._process_and_rank_results(
                raw_results, reference_text[:100], 0.0, limit
            )
            
            return {
                "success": True,
                "reference_text": reference_text[:200] + "..." if len(reference_text) > 200 else reference_text,
                "results": processed_results,
                "total_found": len(processed_results)
            }
            
        except Exception as e:
            print(f"[DocumentSearchEngine] Similar search error: {e}")
            return {
                "success": False,
                "error": str(e),
                "results": []
            }
    
    async def get_document_recommendations(self,
                                         filename: str,
                                         limit: int = 3) -> Dict[str, Any]:
        """
        Get document recommendations based on a reference document.
        
        Args:
            filename: Reference document filename
            limit: Number of recommendations
            
        Returns:
            Recommended documents
        """
        try:
            # First, find the reference document
            ref_results = await self.search_documents(
                query="",  # Empty query, will use filename filter
                filename=filename,
                limit=1
            )
            
            if not ref_results.get("success") or not ref_results.get("results"):
                return {
                    "success": False,
                    "error": f"Reference document not found: {filename}",
                    "recommendations": []
                }
            
            # Use the first chunk of the reference document
            ref_text = ref_results["results"][0]["text"]
            
            # Find similar documents
            similar_results = await self.search_similar_documents(
                reference_text=ref_text,
                exclude_filename=filename,
                limit=limit
            )
            
            return {
                "success": True,
                "reference_filename": filename,
                "recommendations": similar_results.get("results", []),
                "total_recommendations": len(similar_results.get("results", []))
            }
            
        except Exception as e:
            print(f"[DocumentSearchEngine] Recommendations error: {e}")
            return {
                "success": False,
                "error": str(e),
                "recommendations": []
            }
    
    async def _generate_query_embedding(self, query: str) -> Optional[List[float]]:
        """Generate embedding for search query."""
        try:
            def _embed():
                vector = self.embeddings.embed_query(query)
                expected_dim = settings.openai_embed_dim or 1536
                if len(vector) != expected_dim:
                    raise ValueError(f"Expected {expected_dim} dimensions, got {len(vector)}")
                return vector
            
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, _embed)
            
        except Exception as e:
            try:
                print(f"[DocumentSearchEngine] Query embedding error: {e}")
                print(f"[DocumentSearchEngine] Embedding error detail -> type: {type(e).__name__}, repr: {repr(e)}")
                print(f"[DocumentSearchEngine] Current embeddings -> base_url: {settings.openai_base_url}, model: text-embedding-ada-002")
            except Exception:
                pass
            return None
    
    def _get_target_partitions(self, categories: Optional[List[str]]) -> List[str]:
        """Determine which partitions to search based on categories."""
        if not categories:
            # Search all partitions
            return list(self.partition_manager.partitions)
        
        target_partitions = []
        for category in categories:
            if category in self.categories:
                partition_name = self.categories[category]["partition"]
                target_partitions.append(partition_name)
        
        return target_partitions
    
    def _build_filter_expression(self, filename: Optional[str]) -> Optional[str]:
        """Build Milvus filter expression."""
        filters = []
        
        if filename:
            filters.append(f"meta['filename'] == \"{filename}\"")
        
        return " AND ".join(filters) if filters else None
    
    def _process_and_rank_results(self,
                                raw_results: List[Dict[str, Any]],
                                query: str,
                                min_score: float,
                                limit: int) -> List[Dict[str, Any]]:
        """Process and rank search results."""
        processed_results = []
        
        for result in raw_results:
            # Apply score threshold
            meta_for_score = (result.get("metadata", {}) or {})
            # Prefer confidence/similarity from metadata if present; fallback to result.score
            effective_score = None
            try:
                for k in ("confidence", "similarity", "score"):
                    v = meta_for_score.get(k, None) if k != "score" else result.get("score", None)
                    if isinstance(v, (int, float)):
                        effective_score = float(v)
                        break
            except Exception:
                effective_score = result.get("score", 0.0)
            if effective_score is None:
                effective_score = 0.0
            if effective_score < min_score:
                continue
            
            # Enhance result with additional info
            enhanced_result = {
                "id": result.get("id", ""),
                "text": result.get("text", ""),
                "score": effective_score,
                "metadata": result.get("metadata", {}),
                "category": result.get("metadata", {}).get("category", "unknown"),
                "category_name": result.get("metadata", {}).get("category_name", "Unknown"),
                "filename": result.get("metadata", {}).get("filename", ""),
                "page": result.get("metadata", {}).get("page", 0),
                "chunk_index": result.get("metadata", {}).get("chunk_index", 0),
                "upload_time": result.get("metadata", {}).get("upload_time", ""),
            }
            
            # Add snippet preview
            text = enhanced_result["text"]
            if len(text) > 300:
                enhanced_result["snippet"] = text[:300] + "..."
            else:
                enhanced_result["snippet"] = text
            
            processed_results.append(enhanced_result)
        
        # Sort by score (highest first) and limit results
        processed_results.sort(key=lambda x: x["score"], reverse=True)
        return processed_results[:limit]
    
    def _compile_search_stats(self,
                            results: List[Dict[str, Any]],
                            searched_partitions: List[str],
                            query: str) -> Dict[str, Any]:
        """Compile search statistics."""
        stats = {
            "query_length": len(query),
            "partitions_searched": len(searched_partitions),
            "results_by_category": {},
            "average_score": 0.0,
            "score_range": {"min": 1.0, "max": 0.0}
        }
        
        if results:
            # Calculate score statistics
            scores = [r["score"] for r in results]
            stats["average_score"] = sum(scores) / len(scores)
            stats["score_range"]["min"] = min(scores)
            stats["score_range"]["max"] = max(scores)
            
            # Count results by category
            for result in results:
                category = result.get("category", "unknown")
                stats["results_by_category"][category] = stats["results_by_category"].get(category, 0) + 1
        
        return stats
    
    def _check_prerequisites(self) -> bool:
        """Check if search engine is properly initialized."""
        return (
            self.client is not None and
            self.embeddings is not None and
            self.partition_manager is not None
        )
    
    async def get_search_health(self) -> Dict[str, Any]:
        """Get search engine health status."""
        health = {
            "engine_status": "healthy" if self._check_prerequisites() else "degraded",
            "milvus_connected": self.client is not None,
            "embeddings_available": self.embeddings is not None,
            "available_categories": list(self.categories.keys())
        }
        
        if self.partition_manager:
            health["partition_health"] = await self.partition_manager.health_check()
        
        return health
