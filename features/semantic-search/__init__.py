"""
Semantic Search feature module.

Provides configurable NL filter extraction, intent detection,
LLM query rewriting, and Vector Search orchestration with
multi-signal re-ranking.
"""

from .filters import (
    FilterField,
    FilterRegistry,
    extract_filters,
    build_vs_filter_dict,
    fuzzy_match,
)
from .intents import (
    IntentConfig,
    detect_intents,
    get_intent_boost_fields,
    DEFAULT_INTENT_CONFIGS,
)
from .rewriter import (
    QueryRewriter,
    DEFAULT_REWRITE_PROMPT,
)
from .search import (
    SearchConfig,
    SemanticSearchPipeline,
    embed_query,
    aembed_query,
    query_vector_search,
    aquery_vector_search,
    rerank_results,
)

__all__ = [
    # Filters
    "FilterField",
    "FilterRegistry",
    "extract_filters",
    "build_vs_filter_dict",
    "fuzzy_match",
    # Intents
    "IntentConfig",
    "detect_intents",
    "get_intent_boost_fields",
    "DEFAULT_INTENT_CONFIGS",
    # Rewriter
    "QueryRewriter",
    "DEFAULT_REWRITE_PROMPT",
    # Search
    "SearchConfig",
    "SemanticSearchPipeline",
    "embed_query",
    "aembed_query",
    "query_vector_search",
    "aquery_vector_search",
    "rerank_results",
]
