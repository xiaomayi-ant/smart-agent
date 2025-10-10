"""
Intelligent document classifier using Transformers for PDF categorization.
"""
import asyncio
import re
from typing import Dict, List, Optional, Any
from langchain_community.document_loaders import PyPDFLoader

try:
    from transformers import pipeline
    import torch
    TRANSFORMERS_AVAILABLE = True
except ImportError:
    TRANSFORMERS_AVAILABLE = False

# Document category definitions
DOCUMENT_CATEGORIES = {
    "finance": {
        "name": "金融财经",
        "partition": "partition_finance",
        "keywords": ["finance", "financial", "investment", "banking", "stock", "market", "economy", "trading", "金融", "投资", "银行", "股票", "市场", "经济"],
        "description": "Financial documents, investment reports, market analysis"
    },
    "ai": {
        "name": "人工智能", 
        "partition": "partition_ai",
        "keywords": ["artificial intelligence", "machine learning", "deep learning", "neural network", "ai", "ml", "dl", "algorithm", "人工智能", "机器学习", "深度学习", "神经网络", "算法"],
        "description": "AI research papers, ML tutorials, algorithm documentation"
    },
    "blockchain": {
        "name": "区块链加密货币",
        "partition": "partition_blockchain", 
        "keywords": ["blockchain", "cryptocurrency", "bitcoin", "ethereum", "defi", "nft", "smart contract", "crypto", "区块链", "加密货币", "比特币", "以太坊", "智能合约"],
        "description": "Blockchain technology, cryptocurrency analysis, DeFi protocols"
    },
    "robotics": {
        "name": "机器人技术",
        "partition": "partition_robotics",
        "keywords": ["robotics", "robot", "automation", "autonomous", "drone", "robotic", "机器人", "自动化", "无人机", "自主"],
        "description": "Robotics research, automation systems, autonomous vehicles"
    },
    "technology": {
        "name": "科技通用",
        "partition": "partition_technology",
        "keywords": ["technology", "software", "hardware", "computing", "internet", "programming", "tech", "科技", "软件", "硬件", "计算", "互联网", "编程"],
        "description": "General technology documents, software engineering, computing"
    },
    "general": {
        "name": "通用文档",
        "partition": "partition_general",
        "keywords": [],
        "description": "General documents that don't fit other categories"
    }
}


class DocumentClassifier:
    """Intelligent document classifier using Transformers and keyword matching."""
    
    def __init__(self):
        self.classifier = None
        self.categories = DOCUMENT_CATEGORIES
        self._init_classifier()
    
    def _init_classifier(self):
        """Initialize the Transformers classifier."""
        if not TRANSFORMERS_AVAILABLE:
            return
        
        try:
            # Use a lightweight but effective model for text classification
            self.classifier = pipeline(
                "zero-shot-classification",
                model="facebook/bart-large-mnli",
                device=0 if torch.cuda.is_available() else -1,
                torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32
            )
            
        except Exception as e:
            self.classifier = None
    
    async def classify_pdf(self, pdf_path: str, filename: str) -> Dict[str, Any]:
        """
        Classify a PDF document into predefined categories.
        
        Args:
            pdf_path: Path to the PDF file
            filename: Original filename
            
        Returns:
            Classification result with category, partition, confidence, etc.
        """
        try:
            # 1. Extract PDF content summary
            content_summary = await self._extract_pdf_abstract(pdf_path)
            
            if not content_summary:
                return self._get_default_classification(filename)
            
            # 2. Perform classification
            if self.classifier and TRANSFORMERS_AVAILABLE:
                # Use Transformers for enhanced classification
                classification_result = await self._classify_with_transformers(content_summary)
            else:
                # Fallback to keyword-based classification
                classification_result = self._classify_with_keywords(content_summary)
            
            # 3. Map to partition
            partition_info = self._map_to_partition(classification_result)
            
            return {
                "success": True,
                "category": partition_info["category"],
                "partition_name": partition_info["partition"],
                "category_name": partition_info["name"],
                "confidence": classification_result["confidence"],
                "summary": content_summary[:200] + "..." if len(content_summary) > 200 else content_summary,
                "filename": filename,
                "method": classification_result.get("method", "unknown")
            }
            
        except Exception as e:
            return self._get_default_classification(filename, error=str(e))
    
    async def _extract_pdf_abstract(self, pdf_path: str) -> str:
        """Extract abstract and keywords from PDF."""
        try:
            loader = PyPDFLoader(pdf_path)
            documents = loader.load()
            
            if not documents:
                return ""
            
            # Combine first 2 pages for analysis
            full_content = ""
            for doc in documents[:2]:
                full_content += doc.page_content
            
            # 1. Try to extract abstract section
            abstract = self._extract_abstract_section(full_content)
            if abstract:
                return abstract
            
            # 2. Try to extract keywords and title
            keywords_title = self._extract_keywords_and_title(full_content)
            if keywords_title:
                return keywords_title
            
            # 3. Fallback to first 300 characters
            return full_content[:300].strip()
            
        except Exception as e:
            return ""
    
    def _extract_abstract_section(self, content: str) -> str:
        """Extract abstract section from document content."""
        content_lower = content.lower()
        
        # Abstract indicators in multiple languages
        abstract_patterns = [
            r"abstract\s*:?\s*\n",
            r"摘\s*要\s*:?\s*\n",
            r"summary\s*:?\s*\n", 
            r"概\s*述\s*:?\s*\n",
            r"résumé\s*:?\s*\n"
        ]
        
        for pattern in abstract_patterns:
            match = re.search(pattern, content_lower)
            if match:
                start_pos = match.end()
                # Extract abstract content (next 500 characters)
                abstract_text = content[start_pos:start_pos + 500]
                
                # Find abstract end markers
                end_patterns = [
                    r"\n\s*1\.", r"\nintroduction", r"\n引言", 
                    r"\nkeywords", r"\n关键词", r"\nkey\s*words"
                ]
                
                min_end = len(abstract_text)
                for end_pattern in end_patterns:
                    end_match = re.search(end_pattern, abstract_text.lower())
                    if end_match and end_match.start() > 50:
                        min_end = min(min_end, end_match.start())
                
                result = abstract_text[:min_end].strip()
                if len(result) > 50:  # Ensure we have substantial content
                    return result
        
        return ""
    
    def _extract_keywords_and_title(self, content: str) -> str:
        """Extract title and keywords from document content."""
        lines = content.split('\n')[:15]  # Check first 15 lines
        extracted_parts = []
        
        # 1. Extract title (usually in first few lines)
        for line in lines:
            line = line.strip()
            if 10 < len(line) < 200 and not line.lower().startswith(('page', 'doi:', 'http', 'www')):
                # Simple heuristic to identify titles
                if not re.search(r'\d{4}', line):  # Avoid lines with years
                    extracted_parts.append(f"Title: {line}")
                    break
        
        # 2. Extract keywords section
        keyword_patterns = [
            r"keywords?\s*:?\s*(.{1,300})",
            r"关键词\s*:?\s*(.{1,300})",
            r"key\s*words?\s*:?\s*(.{1,300})"
        ]
        
        for pattern in keyword_patterns:
            match = re.search(pattern, content.lower())
            if match:
                keywords = match.group(1).strip()
                # Clean up keywords (remove newlines, extra spaces)
                keywords = re.sub(r'\s+', ' ', keywords)
                if len(keywords) > 10:
                    extracted_parts.append(f"Keywords: {keywords}")
                    break
        
        # 3. If nothing found, extract first meaningful paragraph
        if not extracted_parts:
            for line in lines:
                line = line.strip()
                if len(line) > 100:  # Find a substantial line
                    extracted_parts.append(line[:200])
                    break
        
        return " | ".join(extracted_parts)
    
    async def _classify_with_transformers(self, text: str) -> Dict[str, Any]:
        """Classify text using Transformers model."""
        try:
            # Prepare candidate labels
            candidate_labels = [
                "finance and economics",
                "artificial intelligence and machine learning",
                "blockchain and cryptocurrency", 
                "robotics and automation",
                "technology and software engineering",
                "general academic research"
            ]
            
            def _classify():
                result = self.classifier(text, candidate_labels)
                return {
                    "predicted_label": result["labels"][0],
                    "confidence": result["scores"][0],
                    "all_scores": list(zip(result["labels"], result["scores"])),
                    "method": "transformers"
                }
            
            # Run classification in executor to avoid blocking
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, _classify)
            
        except Exception as e:
            # Fallback to keyword classification
            return self._classify_with_keywords(text)
    
    def _classify_with_keywords(self, text: str) -> Dict[str, Any]:
        """Classify text using keyword matching."""
        text_lower = text.lower()
        category_scores = {}
        
        # Score each category based on keyword matches
        for category, info in self.categories.items():
            if category == "general":
                continue
                
            score = 0
            keywords = info["keywords"]
            
            for keyword in keywords:
                # Count keyword occurrences with weight
                count = text_lower.count(keyword.lower())
                score += count * (2 if len(keyword) > 5 else 1)  # Longer keywords get more weight
            
            if score > 0:
                category_scores[category] = score
        
        # Determine best category
        if category_scores:
            best_category = max(category_scores.items(), key=lambda x: x[1])
            max_score = best_category[1]
            total_score = sum(category_scores.values())
            confidence = min(0.9, max_score / max(total_score, 1))
            
            return {
                "predicted_label": best_category[0],
                "confidence": confidence,
                "all_scores": list(category_scores.items()),
                "method": "keywords"
            }
        else:
            return {
                "predicted_label": "general",
                "confidence": 0.5,
                "all_scores": [],
                "method": "keywords"
            }
    
    def _map_to_partition(self, classification_result: Dict[str, Any]) -> Dict[str, str]:
        """Map classification result to partition information."""
        predicted_label = classification_result["predicted_label"].lower()
        
        # Map Transformers labels to our categories
        if "finance" in predicted_label or "economic" in predicted_label:
            category = "finance"
        elif "artificial" in predicted_label or "machine learning" in predicted_label:
            category = "ai"
        elif "blockchain" in predicted_label or "crypto" in predicted_label:
            category = "blockchain"
        elif "robot" in predicted_label or "automation" in predicted_label:
            category = "robotics"
        elif "technology" in predicted_label or "software" in predicted_label:
            category = "technology"
        elif predicted_label in self.categories:
            category = predicted_label
        else:
            category = "general"
        
        return {
            "category": category,
            "partition": self.categories[category]["partition"],
            "name": self.categories[category]["name"]
        }
    
    def _get_default_classification(self, filename: str, error: Optional[str] = None) -> Dict[str, Any]:
        """Return default classification result."""
        return {
            "success": False,
            "category": "general",
            "partition_name": "partition_general", 
            "category_name": "通用文档",
            "confidence": 0.5,
            "summary": f"Failed to classify document: {filename}" + (f" Error: {error}" if error else ""),
            "filename": filename,
            "method": "default"
        }
    
    def get_categories_info(self) -> Dict[str, Dict[str, str]]:
        """Get information about all available categories."""
        return {
            category: {
                "name": info["name"],
                "partition": info["partition"],
                "description": info["description"]
            }
            for category, info in self.categories.items()
        }
