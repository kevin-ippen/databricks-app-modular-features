"""
Semantic Search feature module.

Provides configurable NL filter extraction, intent detection,
LLM query rewriting, and Vector Search orchestration.
"""

from .filters import FilterConfig, extract_filters, build_vs_filter_dict
from .intents import detect_intents, DEFAULT_INTENT_KEYWORDS
from .rewriter import QueryRewriter, DEFAULT_REWRITE_PROMPT
from .search import SearchConfig, SemanticSearchPipeline, embed_query, query_vector_search, rerank_results

__all__ = [
    # Filters
    "FilterConfig",
    "extract_filters",
    "build_vs_filter_dict",
    # Intents
    "detect_intents",
    "DEFAULT_INTENT_KEYWORDS",
    # Rewriter
    "QueryRewriter",
    "DEFAULT_REWRITE_PROMPT",
    # Search
    "SearchConfig",
    "SemanticSearchPipeline",
    "embed_query",
    "query_vector_search",
    "rerank_results",
]
