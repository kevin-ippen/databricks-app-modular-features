"""
RAG Retriever feature module.

Provides multi-query decomposition, Vector Search retrieval,
citation extraction, and grounded response generation.
"""

from .query_decomposer import (
    FilterOperator,
    FilterClause,
    StructuredQuery,
    decompose_query,
    decompose_query_sync,
    parse_json_response,
)
from .citations import (
    extract_citation_refs,
    build_citation_list,
    format_citations,
    format_inline_citations,
)
from .retriever import RAGRetriever

__all__ = [
    # Query decomposition
    "FilterOperator",
    "FilterClause",
    "StructuredQuery",
    "decompose_query",
    "decompose_query_sync",
    "parse_json_response",
    # Citations
    "extract_citation_refs",
    "build_citation_list",
    "format_citations",
    "format_inline_citations",
    # Retriever
    "RAGRetriever",
]
