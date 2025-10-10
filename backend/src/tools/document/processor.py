"""
PDF document processor with intelligent classification and vector storage.
Handles PDF parsing, text chunking, embedding generation, and Milvus storage.
"""
import asyncio
import os
import tempfile
from datetime import datetime
from typing import List, Dict, Any, Optional
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings
from pymilvus import MilvusClient

from .classifier import DocumentClassifier
from .partition_manager import PartitionManager
from ...core.config import get_milvus_config, settings


class PDFProcessor:
    """
    Comprehensive PDF processing pipeline:
    PDF → Classification → Text Chunking → Embedding → Partition Storage
    """
    
    def __init__(self):
        # Initialize components
        self.milvus_config = get_milvus_config()
        self.client = None
        self.embeddings = None
        self.classifier = DocumentClassifier()
        self.partition_manager = None
        
        # Text splitter configuration
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=200,
            separators=["\n\n", "\n", "。", "！", "？", ".", " ", ""],
            length_function=len,
        )
        
        self._init_connections()
    
    def _init_connections(self):
        """Initialize Milvus and OpenAI connections."""
        try:
            # Initialize Milvus client
            if self.milvus_config.get("address"):
                self.client = MilvusClient(
                    uri=f"http://{self.milvus_config['address']}"
                )
                self.partition_manager = PartitionManager(self.client)
                print("[PDFProcessor] Milvus connection initialized")
            else:
                print("[PDFProcessor] Milvus address not configured")
                
            # Initialize OpenAI embeddings
            # Prefer embeddings-specific credentials if provided
            effective_api_key = settings.openai_embed_api_key or settings.openai_api_key
            effective_base_url = settings.openai_embed_base_url or settings.openai_base_url
            if effective_api_key:
                self.embeddings = OpenAIEmbeddings(
                    openai_api_key=effective_api_key,
                    base_url=effective_base_url,
                    model=(settings.openai_embed_model or "text-embedding-3-small")
                )
                print("[PDFProcessor] OpenAI embeddings initialized")
                try:
                    print(f"[PDFProcessor] Embeddings config -> base_url: {effective_base_url}, model: {settings.openai_embed_model or 'text-embedding-3-small'}")
                except Exception:
                    pass
            else:
                print("[PDFProcessor] OpenAI API key not configured")
                
        except Exception as e:
            print(f"[PDFProcessor] Initialization error: {e}")
            self.client = None
            self.embeddings = None
            self.partition_manager = None
    
    async def process_pdf_file(self, 
                              file_path: str, 
                              filename: str,
                              user_category: Optional[str] = None,
                              user_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Process a PDF file through the complete pipeline.
        
        Args:
            file_path: Path to the PDF file
            filename: Original filename
            user_category: Optional user-specified category override
            
        Returns:
            Processing result with classification, storage info, etc.
        """
        if not self._check_prerequisites():
            return {
                "success": False,
                "error": "PDF processor not properly initialized",
                "filename": filename
            }
        
        try:
            # Ensure collection and partitions exist
            await self.partition_manager.ensure_collection_and_partitions()
            
            # Step 1: Classify the document
            if user_category:
                classification = self._create_manual_classification(user_category, filename)
            else:
                classification = await self.classifier.classify_pdf(file_path, filename)
            
            if not classification.get("success", True):
                return classification
            
            # Step 2: Extract and chunk text
            chunks = await self._extract_and_chunk_pdf(file_path, filename)
            if not chunks:
                return {
                    "success": False,
                    "error": "Failed to extract text from PDF",
                    "filename": filename
                }
            
            # Step 3: Generate embeddings
            vectors_data = await self._generate_embeddings(chunks, classification, filename, user_id)
            if not vectors_data:
                return {
                    "success": False,
                    "error": "Failed to generate embeddings",
                    "filename": filename
                }
            
            # Step 4: Store in appropriate partition
            partition_name = classification["partition_name"]
            storage_success = await self.partition_manager.insert_document(
                partition_name=partition_name,
                document_data=vectors_data
            )
            
            if not storage_success:
                return {
                    "success": False,
                    "error": "Failed to store document in Milvus",
                    "filename": filename
                }
            
            # Return success result
            return {
                "success": True,
                "filename": filename,
                "category": classification["category"],
                "category_name": classification["category_name"],
                "partition_name": partition_name,
                "confidence": classification["confidence"],
                "chunks_processed": len(chunks),
                "vectors_stored": len(vectors_data),
                "summary": classification.get("summary", ""),
                "processing_method": classification.get("method", "unknown"),
                "timestamp": datetime.now().isoformat()
            }
            
        except Exception as e:
            print(f"[PDFProcessor] Processing error: {e}")
            return {
                "success": False,
                "error": str(e),
                "filename": filename
            }
    
    async def process_pdf_content(self, 
                                 file_content: bytes,
                                 filename: str,
                                 user_category: Optional[str] = None,
                                 user_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Process PDF content from memory (uploaded file).
        
        Args:
            file_content: PDF file content as bytes
            filename: Original filename
            user_category: Optional user-specified category
            
        Returns:
            Processing result
        """
        # Create temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
            tmp_file.write(file_content)
            tmp_file_path = tmp_file.name
        
        try:
            # Process the temporary file
            result = await self.process_pdf_file(tmp_file_path, filename, user_category, user_id)
            return result
            
        finally:
            # Clean up temporary file
            try:
                os.unlink(tmp_file_path)
            except OSError:
                pass
    
    async def _extract_and_chunk_pdf(self, file_path: str, filename: str) -> List[Dict[str, Any]]:
        """Extract text from PDF and split into chunks."""
        try:
            # Load PDF
            loader = PyPDFLoader(file_path)
            documents = loader.load()
            
            if not documents:
                print(f"[PDFProcessor] No content extracted from {filename}")
                return []
            
            # Split documents into chunks
            split_docs = self.text_splitter.split_documents(documents)
            
            # Convert to our format
            chunks = []
            for i, doc in enumerate(split_docs):
                chunks.append({
                    "text": doc.page_content,
                    "metadata": {
                        "filename": filename,
                        "page": doc.metadata.get("page", 0),
                        "chunk_index": i,
                        "source": file_path
                    }
                })
            
            print(f"[PDFProcessor] Extracted {len(chunks)} chunks from {filename}")
            return chunks
            
        except Exception as e:
            print(f"[PDFProcessor] Text extraction error: {e}")
            return []
    
    async def _generate_embeddings(self, 
                                  chunks: List[Dict[str, Any]], 
                                  classification: Dict[str, Any],
                                  filename: str,
                                  user_id: Optional[str]) -> List[Dict[str, Any]]:
        """Generate embeddings for text chunks."""
        try:
            vectors_data = []
            
            for i, chunk in enumerate(chunks):
                # Generate embedding
                vector = await self._generate_single_embedding(chunk["text"])
                
                if vector is None:
                    print(f"[PDFProcessor] Failed to generate embedding for chunk {i}")
                    continue
                
                # Create document record
                doc_id = f"{filename}_{i}_{classification['category']}_{int(datetime.now().timestamp())}"
                
                # Enhanced metadata
                metadata = chunk["metadata"].copy()
                metadata.update({
                    "category": classification["category"],
                    "category_name": classification["category_name"],
                    "confidence": classification["confidence"],
                    "processing_method": classification.get("method", "unknown"),
                    "upload_time": datetime.now().isoformat(),
                    "document_summary": classification.get("summary", "")[:200],  # Truncate summary
                    "doc_id": doc_id,
                    "user_id": user_id or "",
                })
                
                vectors_data.append({
                    # do not set explicit id; let Milvus auto_id generate it
                    "vector": vector,
                    "text": chunk["text"],
                    "metadata": metadata
                })
            
            print(f"[PDFProcessor] Generated {len(vectors_data)} embeddings for {filename}")
            return vectors_data
            
        except Exception as e:
            print(f"[PDFProcessor] Embedding generation error: {e}")
            return []
    
    async def _generate_single_embedding(self, text: str) -> Optional[List[float]]:
        """Generate embedding for a single text chunk."""
        try:
            def _embed():
                vector = self.embeddings.embed_query(text)
                expected_dim = settings.openai_embed_dim or 1536
                if len(vector) != expected_dim:
                    raise ValueError(f"Expected {expected_dim} dimensions, got {len(vector)}")
                return vector
            
            # Run in executor to avoid blocking
            loop = asyncio.get_event_loop()
            vector = await loop.run_in_executor(None, _embed)
            return vector
            
        except Exception as e:
            try:
                print(f"[PDFProcessor] Single embedding error: {e}")
                print(f"[PDFProcessor] Embedding error detail -> type: {type(e).__name__}, repr: {repr(e)}")
                print(f"[PDFProcessor] Current embeddings -> base_url: {settings.openai_base_url}, model: text-embedding-ada-002")
            except Exception:
                pass
            return None
    
    def _create_manual_classification(self, category: str, filename: str) -> Dict[str, Any]:
        """Create classification result for manually specified category."""
        categories_info = self.classifier.get_categories_info()
        
        if category in categories_info:
            return {
                "success": True,
                "category": category,
                "partition_name": categories_info[category]["partition"],
                "category_name": categories_info[category]["name"],
                "confidence": 1.0,  # Manual classification has full confidence
                "summary": f"Manually classified as {category}",
                "filename": filename,
                "method": "manual"
            }
        else:
            # Default to general if invalid category
            return {
                "success": True,
                "category": "general",
                "partition_name": "partition_general",
                "category_name": "通用文档",
                "confidence": 0.8,
                "summary": f"Invalid category '{category}', using general",
                "filename": filename,
                "method": "manual_fallback"
            }
    
    def _check_prerequisites(self) -> bool:
        """Check if all required components are initialized."""
        return (
            self.client is not None and 
            self.embeddings is not None and 
            self.partition_manager is not None
        )
    
    async def get_processing_stats(self) -> Dict[str, Any]:
        """Get processing statistics and health info."""
        if not self.partition_manager:
            return {"error": "Partition manager not initialized"}
        
        try:
            # Get partition statistics
            partition_stats = await self.partition_manager.get_partition_stats()
            
            # Get health check info
            health_info = await self.partition_manager.health_check()
            
            return {
                "processor_status": "healthy" if self._check_prerequisites() else "degraded",
                "milvus_connected": self.client is not None,
                "embeddings_available": self.embeddings is not None,
                "classifier_method": "transformers" if hasattr(self.classifier, 'classifier') and self.classifier.classifier else "keywords",
                "partition_stats": partition_stats,
                "health_check": health_info
            }
            
        except Exception as e:
            return {"error": str(e)}
    
    async def delete_document_by_filename(self, filename: str, user_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Delete all chunks of a document by filename.
        
        Args:
            filename: Original filename to delete
            
        Returns:
            Deletion result
        """
        if not self.partition_manager:
            return {"success": False, "error": "Partition manager not initialized"}
        
        try:
            deleted_count = 0
            
            # Search across all partitions for documents with this filename
            for partition in self.partition_manager.partitions:
                try:
                    # Delete documents matching the filename
                    expr = f'metadata["filename"] == "{filename}"'
                    if user_id:
                        expr = expr + f' and metadata["user_id"] == "{user_id}"'
                    result = self.client.delete(
                        collection_name=settings.documents_collection_name or "documents",
                        expr=expr,
                        partition_names=[partition]
                    )
                    
                    if hasattr(result, 'delete_count'):
                        deleted_count += result.delete_count
                        
                except Exception as e:
                    print(f"[PDFProcessor] Error deleting from {partition}: {e}")
                    continue
            
            return {
                "success": deleted_count > 0,
                "filename": filename,
                "deleted_chunks": deleted_count,
                "message": f"Deleted {deleted_count} chunks" if deleted_count > 0 else "No documents found"
            }
            
        except Exception as e:
            print(f"[PDFProcessor] Delete error: {e}")
            return {
                "success": False,
                "filename": filename,
                "error": str(e)
            }
