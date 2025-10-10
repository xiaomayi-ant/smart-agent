from .sql.mysql_tool import (
    mysql_simple_query_tool,
    mysql_aggregated_query_tool,
    mysql_join_query_tool,
    mysql_custom_query_tool,
)
from .date import date_calculator_tool
from .web.tavily import tavily_search_tool
try:
    from .kg.neo4j_tools import (
        graphiti_search_tool,
        graphiti_add_episode_tool,
        graphiti_add_entity_tool,
        graphiti_add_edge_tool,
        graphiti_ingest_detect_tool,
        graphiti_ingest_commit_tool,
    )
    KG_TOOLS_AVAILABLE = True
except Exception as e:
    KG_TOOLS_AVAILABLE = False

# Document processing tools (new)
try:
    from .document.document_tools import (
        search_documents_tool,
        # search_documents_by_category_tool,
        # list_document_categories_tool,
        # get_document_recommendations_tool,
        # get_document_processing_stats_tool,
        # upload_pdf_tool,  # Available but not registered for AI use
        # delete_document_tool,  # Available but not registered for AI use
    )
    DOCUMENT_TOOLS_AVAILABLE = True
except ImportError as e:
    DOCUMENT_TOOLS_AVAILABLE = False

# Central registry used by graph.py
ALL_TOOLS_LIST = [
    # Core database and search tools
    mysql_simple_query_tool,
    mysql_aggregated_query_tool,
    mysql_join_query_tool,
    mysql_custom_query_tool,
    date_calculator_tool,
    tavily_search_tool,
]

# Add document tools if available
if DOCUMENT_TOOLS_AVAILABLE:
    ALL_TOOLS_LIST.extend([
        search_documents_tool,
        # search_documents_by_category_tool,
        # list_document_categories_tool,
        # get_document_recommendations_tool,
        # get_document_processing_stats_tool,
    ]) 

# Add KG tools if available
if KG_TOOLS_AVAILABLE:
    ALL_TOOLS_LIST.extend([
        graphiti_search_tool,
        graphiti_add_episode_tool,
        graphiti_add_entity_tool,
        graphiti_add_edge_tool,
        graphiti_ingest_detect_tool,
        graphiti_ingest_commit_tool,
    ])

# Fast lookup by tool name - 在所有工具添加完成后构建
TOOL_BY_NAME = {t.name: t for t in ALL_TOOLS_LIST}