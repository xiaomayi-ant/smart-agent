"""
Partition manager for Milvus document collections.
Handles creation, management, and querying of document partitions.
"""
from typing import List, Dict, Optional, Any
from pymilvus import MilvusClient, Collection, connections, utility
from .classifier import DOCUMENT_CATEGORIES
from ...core.config import settings


class PartitionManager:
    """Manages Milvus partitions for document categorization."""
    
    def __init__(self, milvus_client: MilvusClient):
        self.client = milvus_client
        self.collection_name = settings.documents_collection_name or "documents"
        self.partitions = [
            "partition_finance",
            "partition_ai", 
            "partition_blockchain",
            "partition_robotics",
            "partition_technology",
            "partition_general"
        ]
        self.categories = DOCUMENT_CATEGORIES
    
    async def ensure_collection_and_partitions(self) -> bool:
        """
        Ensure the documents collection and all partitions exist.
        Creates them if they don't exist.
        
        Returns:
            True if successful, False otherwise
        """
        try:
            # 1. Check if collection exists, create if not
            collections = self.client.list_collections()
            # Optional reset for schema changes
            if settings.reset_documents_collection_on_startup and self.collection_name in collections:
                try:
                    self.client.drop_collection(self.collection_name)
                    collections = [c for c in collections if c != self.collection_name]
                except Exception as e:
                    print(f"[PartitionManager] Drop collection error: {e}")
            
            if self.collection_name not in collections:
                self._create_documents_collection()
            
            # 2. Ensure all partitions exist
            existing_partitions = self.client.list_partitions(self.collection_name)
            
            for partition_name in self.partitions:
                if partition_name not in existing_partitions:
                    self.client.create_partition(
                        collection_name=self.collection_name,
                        partition_name=partition_name
                    )
            
            # 3. Load collection to make it searchable
            self.client.load_collection(self.collection_name)
            
            return True
            
        except Exception as e:
            print(f"[PartitionManager] Setup error: {e}")
            return False
    
    def _create_documents_collection(self):
        """Create the documents collection with appropriate schema."""
        try:
            # Use MilvusClient's simplified API
            self.client.create_collection(
                collection_name=self.collection_name,
                dimension=(settings.openai_embed_dim or 1536),
                metric_type="COSINE",
                auto_id=True,
                description="Document collection with category-based partitions",
                # Additional parameters for better performance
                consistency_level="Strong",
                enable_dynamic_field=True
            )
            
        except Exception as e:
            print(f"[PartitionManager] Error creating collection: {e}")
            raise
    
    async def insert_document(self, 
                            partition_name: str,
                            document_data: List[Dict[str, Any]]) -> bool:
        """
        Insert document data into specified partition.
        
        Args:
            partition_name: Target partition name
            document_data: List of document vectors and metadata
            
        Returns:
            True if successful, False otherwise
        """
        try:
            if partition_name not in self.partitions:
                raise ValueError(f"Invalid partition name: {partition_name}")
            
            # Pre-insert stats for diagnostics
            prev_count = None
            try:
                prev_stats = self.client.get_partition_stats(
                    collection_name=self.collection_name,
                    partition_name=partition_name
                )
                prev_count = prev_stats.get("row_count", None)
            except Exception as e:
                print(f"[PartitionManager] Pre-insert stats fetch error: {e}")

            # Insert data into specific partition
            insert_result = self.client.insert(
                collection_name=self.collection_name,
                data=document_data,
                partition_name=partition_name
            )
            
            # Diagnostic: print insert result summary
            try:
                insert_count = getattr(insert_result, 'insert_count', None)
                ids_preview = None
                if hasattr(insert_result, 'primary_keys'):
                    ids = getattr(insert_result, 'primary_keys')
                    if isinstance(ids, list):
                        ids_preview = ids[:3]
                print(f"[PartitionManager] Insert result -> requested: {len(document_data)}, inserted: {insert_count}, ids_preview: {ids_preview}")
            except Exception:
                pass

            # Post-insert stats for diagnostics
            try:
                post_stats = self.client.get_partition_stats(
                    collection_name=self.collection_name,
                    partition_name=partition_name
                )
                post_count = post_stats.get("row_count", None)
                print(f"[PartitionManager] Partition '{partition_name}' row_count: before={prev_count}, after={post_count}")
            except Exception as e:
                print(f"[PartitionManager] Post-insert stats fetch error: {e}")

            print(f"[PartitionManager] Inserted {len(document_data)} documents into {partition_name}")
            return True
            
        except Exception as e:
            print(f"[PartitionManager] Insert error: {e}")
            return False
    
    async def search_partitions(self, 
                              query_vector: List[float],
                              partitions: Optional[List[str]] = None,
                              limit: int = 5,
                              filter_expr: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Search across specified partitions.
        
        Args:
            query_vector: Query embedding vector
            partitions: List of partition names to search (None = all)
            limit: Maximum number of results
            filter_expr: Optional filter expression
            
        Returns:
            List of search results with metadata
        """
        try:
            search_partitions = partitions or self.partitions
            
            # Validate partition names
            valid_partitions = [p for p in search_partitions if p in self.partitions]
            if not valid_partitions:
                return []
            
            search_params = {
                "collection_name": self.collection_name,
                "data": [query_vector],
                "search_params": {"metric_type": "COSINE", "nprobe": 10},
                "limit": limit,
                "output_fields": ["$meta"],
                "partition_names": valid_partitions,
                "anns_field": "vector"
            }
            
            if filter_expr:
                search_params["filter"] = filter_expr

            # TRACE：打印最终 Milvus 搜索参数摘要（不包含向量内容）
            try:
                from ...core.config import settings as _settings  # lazy import; avoid top-level import
                if getattr(_settings, 'trace_events', False):
                    print(f"[PartitionManager] search partitions={valid_partitions} limit={limit} filter={filter_expr}")
            except Exception:
                pass
            
            results = self.client.search(**search_params)
            
            return self._process_search_results(results)
            
        except Exception as e:
            print(f"[PartitionManager] Search error: {e}")
            return []
    
    def _process_search_results(self, results: List[List[Dict]]) -> List[Dict[str, Any]]:
        """Process and format search results."""
        processed_results = []
        
        try:
            # results is a list of lists (one list per query)
            for result_list in results:
                for result in result_list:
                    if "entity" in result:
                        entity = result["entity"]
                        meta = entity.get("$meta", {}) if isinstance(entity, dict) else {}
                        # 规范解包：text 在 $meta["text"]；业务元数据在 $meta["metadata"]
                        meta_metadata = {}
                        if isinstance(meta, dict):
                            meta_metadata = meta.get("metadata", {}) if isinstance(meta.get("metadata"), dict) else {}
                        # Build backward-compatible shape
                        processed_results.append({
                            "text": meta.get("text", entity.get("text", "")),
                            "metadata": meta_metadata if meta_metadata else entity.get("metadata", {}),
                            "score": result.get("score", 0.0),
                            "id": result.get("id", "")
                        })
            
        except Exception as e:
            print(f"[PartitionManager] Result processing error: {e}")
        
        return processed_results
    
    async def delete_document(self, document_id: str, partition_name: Optional[str] = None) -> bool:
        """
        Delete a document by ID.
        
        Args:
            document_id: Document ID to delete
            partition_name: Specific partition to delete from (None = search all)
            
        Returns:
            True if successful, False otherwise
        """
        try:
            delete_params = {
                "collection_name": self.collection_name,
                "expr": f"id == '{document_id}'"
            }
            
            if partition_name:
                delete_params["partition_names"] = [partition_name]
            
            result = self.client.delete(**delete_params)
            
            print(f"[PartitionManager] Deleted document: {document_id}")
            return True
            
        except Exception as e:
            print(f"[PartitionManager] Delete error: {e}")
            return False
    
    async def get_partition_stats(self) -> Dict[str, Any]:
        """
        Get statistics for all partitions.
        
        Returns:
            Dictionary with partition statistics
        """
        stats = {
            "total_partitions": len(self.partitions),
            "partitions": {}
        }
        
        try:
            for partition_name in self.partitions:
                try:
                    # Get partition info
                    partition_stats = self.client.get_partition_stats(
                        collection_name=self.collection_name,
                        partition_name=partition_name
                    )
                    
                    # Find category info
                    category_info = None
                    for category, info in self.categories.items():
                        if info["partition"] == partition_name:
                            category_info = info
                            break
                    
                    stats["partitions"][partition_name] = {
                        "row_count": partition_stats.get("row_count", 0),
                        "category_name": category_info["name"] if category_info else "Unknown",
                        "description": category_info["description"] if category_info else ""
                    }
                    
                except Exception as e:
                    print(f"[PartitionManager] Error getting stats for {partition_name}: {e}")
                    stats["partitions"][partition_name] = {
                        "row_count": 0,
                        "error": str(e)
                    }
            
        except Exception as e:
            print(f"[PartitionManager] Error getting partition stats: {e}")
            stats["error"] = str(e)
        
        return stats
    
    async def list_documents_in_partition(self, 
                                        partition_name: str,
                                        limit: int = 10,
                                        offset: int = 0) -> List[Dict[str, Any]]:
        """
        List documents in a specific partition.
        
        Args:
            partition_name: Partition to query
            limit: Maximum number of documents to return
            offset: Number of documents to skip
            
        Returns:
            List of document metadata
        """
        try:
            if partition_name not in self.partitions:
                raise ValueError(f"Invalid partition name: {partition_name}")
            
            results = self.client.query(
                collection_name=self.collection_name,
                filter="",  # No filter, get all documents
                output_fields=["id", "metadata"],
                partition_names=[partition_name],
                limit=limit,
                offset=offset
            )
            
            return results
            
        except Exception as e:
            print(f"[PartitionManager] List documents error: {e}")
            return []
    
    def get_partition_for_category(self, category: str) -> Optional[str]:
        """
        Get partition name for a given category.
        
        Args:
            category: Category name
            
        Returns:
            Partition name or None if not found
        """
        if category in self.categories:
            return self.categories[category]["partition"]
        return None
    
    def get_category_for_partition(self, partition_name: str) -> Optional[str]:
        """
        Get category name for a given partition.
        
        Args:
            partition_name: Partition name
            
        Returns:
            Category name or None if not found
        """
        for category, info in self.categories.items():
            if info["partition"] == partition_name:
                return category
        return None
    
    async def health_check(self) -> Dict[str, Any]:
        """
        Perform health check on the collection and partitions.
        
        Returns:
            Health status information
        """
        health_info = {
            "collection_exists": False,
            "collection_loaded": False,
            "partitions_status": {},
            "total_documents": 0
        }
        
        try:
            # Check collection existence
            collections = self.client.list_collections()
            health_info["collection_exists"] = self.collection_name in collections
            
            if health_info["collection_exists"]:
                # Check if collection is loaded
                try:
                    # Try a simple query to check if loaded
                    self.client.query(
                        collection_name=self.collection_name,
                        filter="",
                        limit=1
                    )
                    health_info["collection_loaded"] = True
                except:
                    health_info["collection_loaded"] = False
                
                # Check partitions
                existing_partitions = self.client.list_partitions(self.collection_name)
                for partition_name in self.partitions:
                    health_info["partitions_status"][partition_name] = partition_name in existing_partitions
                
                # Get total document count
                stats = await self.get_partition_stats()
                health_info["total_documents"] = sum(
                    p.get("row_count", 0) for p in stats.get("partitions", {}).values()
                    if isinstance(p, dict) and "row_count" in p
                )
        
        except Exception as e:
            health_info["error"] = str(e)
        
        return health_info
