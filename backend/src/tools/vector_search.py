"""
Vector search utilities using Milvus
"""
import asyncio
from typing import List, Dict, Any, Optional
from pymilvus import MilvusClient, connections
from langchain_openai import OpenAIEmbeddings
from ..core.config import get_milvus_config, settings


class VectorSearchManager:
    """Milvus vector search manager"""
    
    def __init__(self):
        self.config = get_milvus_config()
        self.client = None
        self.embeddings = None
        self._init_connections()
    
    def _init_connections(self):
        """Initialize Milvus and OpenAI connections"""
        try:
            # Initialize client
            self.client = MilvusClient(
                uri=f"http://{self.config['address']}"
            )
            
            # Initialize embeddings
            self.embeddings = OpenAIEmbeddings(
                openai_api_key=settings.openai_api_key,
                model="text-embedding-ada-002"
            )
        except Exception as e:
            print(f"[VectorSearch] Failed to initialize Milvus connection: {e}")
            print(f"[VectorSearch] Vector search features will be disabled")
            self.client = None
            self.embeddings = None
    
    async def generate_embedding(self, text: str) -> List[float]:
        """Generate embedding for text"""
        def _generate():
            try:
                vector = self.embeddings.embed_query(text)
                if len(vector) != 1536:
                    raise ValueError(f"Query vector dimension mismatch. Expected 1536, but got {len(vector)}")
                return vector
            except Exception as e:
                print(f'Error generating embedding: {e}')
                raise
        
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _generate)
    
    async def hybrid_search(self, query: str = None, publish_time: str = None, limit: int = 3) -> List[Dict[str, Any]]:
        """Perform hybrid search with vector and metadata filtering"""
        try:
            # Handle empty query
            effective_query = query.strip() if query and query.strip() else None
            
            if not effective_query and not publish_time:
                raise ValueError('At least one of "query" or "publishTime" must be provided')
            
            # Load collection
            self.client.load_collection(collection_name="cls")
            
            # Prepare search parameters
            output_fields = ['text', 'metadata']
            
            if effective_query and publish_time:
                # Hybrid search: vector + metadata filtering
                query_vector = await self.generate_embedding(effective_query)
                
                # Generate date patterns
                year = publish_time[:4]
                month = publish_time[5:7]
                day = publish_time[8:10]
                
                date_patterns = [
                    f"{year}-{month}-{day}",
                    f"{year}.{month}.{day}",
                    f"{year}/{month}/{day}"
                ]
                
                # Build filter expression
                date_filter = " or ".join([f'metadata["publishTime"] == "{pattern}"' for pattern in date_patterns])
                
                results = self.client.search(
                    collection_name="cls",
                    data=[query_vector],
                    anns_field="vector",
                    param={"metric_type": "COSINE", "params": {"nprobe": 10}},
                    limit=limit,
                    output_fields=output_fields,
                    expr=date_filter
                )
                
            elif effective_query:
                # Vector search only
                query_vector = await self.generate_embedding(effective_query)
                
                results = self.client.search(
                    collection_name="cls",
                    data=[query_vector],
                    anns_field="vector",
                    param={"metric_type": "COSINE", "params": {"nprobe": 10}},
                    limit=limit,
                    output_fields=output_fields
                )
                
            else:
                # Metadata search only
                year = publish_time[:4]
                month = publish_time[5:7]
                day = publish_time[8:10]
                
                date_patterns = [
                    f"{year}-{month}-{day}",
                    f"{year}.{month}.{day}",
                    f"{year}/{month}/{day}"
                ]
                
                date_filter = " or ".join([f'metadata["publishTime"] == "{pattern}"' for pattern in date_patterns])
                
                results = self.client.query(
                    collection_name="cls",
                    filter_=date_filter,
                    output_fields=output_fields,
                    limit=limit
                )
                # Convert query results to search format
                results = [{"entity": {"text": r["text"], "metadata": r["metadata"]}} for r in results]
            
            # Process results
            processed_results = []
            for result in results:
                if "entity" in result:
                    entity = result["entity"]
                    processed_results.append({
                        "text": entity.get("text", ""),
                        "metadata": entity.get("metadata", {}),
                        "score": result.get("score", 0.0)
                    })
            
            return processed_results
            
        except Exception as e:
            print(f"[VectorSearch] Search error: {e}")
            raise


# Global vector search manager instance
vector_search_manager = VectorSearchManager()


async def hybrid_milvus_search(query: str = None, publish_time: str = None, limit: int = 3) -> List[Dict[str, Any]]:
    """Hybrid Milvus search tool"""
    return await vector_search_manager.hybrid_search(query, publish_time, limit) 