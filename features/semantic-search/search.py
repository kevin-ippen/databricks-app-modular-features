"""
Semantic search orchestration.

Coordinates: embedding -> Vector Search -> re-ranking with configurable weights.
All configuration (endpoints, indexes, models) is injected — no hardcoded references.
"""

import json
import logging
import time
from typing import Optional, Callable, Any

import numpy as np
import requests

from .filters import FilterConfig, extract_filters, build_vs_filter_dict
from .intents import detect_intents
from .rewriter import QueryRewriter

logger = logging.getLogger(__name__)


# ── Configuration ─────────────────────────────────────────────────────────────

class SearchConfig:
    """
    Configuration for the semantic search pipeline.

    All workspace-specific values are injected here rather than hardcoded.
    """

    def __init__(
        self,
        workspace_host: str,
        vs_endpoint: str,
        vs_index: str,
        embedding_model: str,
        token_provider: Callable[[], str],
        *,
        rewrite_model: Optional[str] = None,
        rewrite_prompt: Optional[str] = None,
        ranking_weights: Optional[dict[str, float]] = None,
        filter_config: Optional[FilterConfig] = None,
        intent_keywords: Optional[dict[str, set[str]]] = None,
        substring_intents: Optional[dict[str, list[str]]] = None,
        vs_columns: Optional[list[str]] = None,
        filter_column_mapping: Optional[dict[str, dict]] = None,
        overfetch_factor: int = 3,
        default_limit: int = 10,
        max_results: int = 20,
    ):
        self.workspace_host = workspace_host.rstrip("/")
        self.vs_endpoint = vs_endpoint
        self.vs_index = vs_index
        self.embedding_model = embedding_model
        self.token_provider = token_provider
        self.rewrite_model = rewrite_model
        self.rewrite_prompt = rewrite_prompt

        # Ranking weights: keys are signal names, values are 0-1 weights summing to ~1.0
        self.ranking_weights = ranking_weights or {
            "vs_score": 0.50,
            "metadata_score": 0.25,
            "intent_bonus": 0.15,
            "secondary_score": 0.10,
        }

        self.filter_config = filter_config or FilterConfig()
        self.intent_keywords = intent_keywords
        self.substring_intents = substring_intents

        # Columns to retrieve from Vector Search
        self.vs_columns = vs_columns or ["doc_id", "content", "title", "url"]

        # Maps extracted filter names -> VS filter column + operator
        self.filter_column_mapping = filter_column_mapping or {}

        self.overfetch_factor = overfetch_factor
        self.default_limit = default_limit
        self.max_results = max_results


# ── Core search functions ─────────────────────────────────────────────────────

def embed_query(text: str, config: SearchConfig) -> list[float]:
    """
    Embed a single query string via the configured embedding endpoint.

    Returns a normalized float list (unit vector).
    """
    token = config.token_provider()
    resp = requests.post(
        f"{config.workspace_host}/serving-endpoints/{config.embedding_model}/invocations",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json={"input": [text]},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()["data"]
    emb = np.array(data[0]["embedding"], dtype=np.float32)
    norm = np.linalg.norm(emb)
    if norm > 0:
        emb = emb / norm
    return emb.tolist()


def query_vector_search(
    embedding: list[float],
    config: SearchConfig,
    top_k: int,
    vs_filter: Optional[dict] = None,
) -> list[dict]:
    """
    Query a Databricks Vector Search index.

    Args:
        embedding: Query embedding vector.
        config: SearchConfig with endpoint details.
        top_k: Number of results (will be multiplied by overfetch_factor internally).
        vs_filter: Optional VS filter dict.

    Returns:
        List of result dicts with columns from config.vs_columns + score.
    """
    body: dict[str, Any] = {
        "query_vector": embedding,
        "columns": config.vs_columns,
        "num_results": top_k * config.overfetch_factor,
    }

    if vs_filter:
        body["filters_json"] = json.dumps(vs_filter)

    token = config.token_provider()
    resp = requests.post(
        f"{config.workspace_host}/api/2.0/vector-search/indexes/{config.vs_index}/query",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json=body,
        timeout=30,
    )

    if resp.status_code == 404:
        logger.warning("VS index not found — returning empty results")
        return []

    resp.raise_for_status()
    result = resp.json()

    # Parse VS response format
    manifest = result.get("manifest", {})
    columns = [c.get("name") for c in manifest.get("columns", [])]
    data_array = result.get("result", {}).get("data_array", [])

    return [dict(zip(columns, row)) for row in data_array]


def rerank_results(
    rows: list[dict],
    query: str,
    config: SearchConfig,
    intents: dict[str, float],
    top_k: int,
    score_fn: Optional[Callable[[dict, str, dict[str, float]], float]] = None,
) -> list[dict]:
    """
    Re-rank Vector Search results using configurable weights.

    Args:
        rows: Raw VS results with a 'score' field.
        query: Original user query (for match reason generation).
        config: SearchConfig with ranking_weights.
        intents: Detected intent signals.
        top_k: Number of results to return after re-ranking.
        score_fn: Optional custom scoring function (row, query, intents) -> float.
                  If not provided, uses default VS score weighting.

    Returns:
        Top-k results sorted by final_rank_score (descending).
    """
    weights = config.ranking_weights

    ranked = []
    for row in rows:
        vs_score = float(row.get("score", 0) or 0)

        if score_fn:
            final_score = score_fn(row, query, intents)
        else:
            # Default: weight the VS score as primary signal
            final_score = weights.get("vs_score", 0.5) * vs_score

            # Intent bonus: flat boost if any intent matches metadata
            if intents:
                intent_bonus = 0.1 if intents else 0.0
                final_score += weights.get("intent_bonus", 0.15) * intent_bonus

        row["final_rank_score"] = round(final_score, 4)
        ranked.append(row)

    ranked.sort(key=lambda r: r.get("final_rank_score", 0), reverse=True)
    return ranked[:top_k]


# ── High-level orchestrator ───────────────────────────────────────────────────

class SemanticSearchPipeline:
    """
    End-to-end semantic search pipeline.

    Orchestrates: query parsing -> intent detection -> rewriting ->
    embedding -> VS query -> re-ranking.
    """

    def __init__(self, config: SearchConfig):
        self.config = config
        self._rewriter: Optional[QueryRewriter] = None

        if config.rewrite_model:
            self._rewriter = QueryRewriter(
                workspace_host=config.workspace_host,
                model_name=config.rewrite_model,
                token_provider=config.token_provider,
                system_prompt=config.rewrite_prompt,
            )

    def search(
        self,
        query: str,
        top_k: Optional[int] = None,
        extra_filters: Optional[dict] = None,
        score_fn: Optional[Callable[[dict, str, dict[str, float]], float]] = None,
    ) -> dict[str, Any]:
        """
        Execute a full search pipeline.

        Args:
            query: User query string.
            top_k: Number of results. Defaults to config.default_limit.
            extra_filters: Additional VS filter dict to merge with extracted filters.
            score_fn: Optional custom scoring function for re-ranking.

        Returns:
            Dict with keys: results, filters_extracted, intents, query_expanded,
            total_candidates, retrieval_ms.
        """
        t0 = time.time()
        top_k = min(top_k or self.config.default_limit, self.config.max_results)

        # 1. Extract NL filters
        filters_extracted, cleaned_q = extract_filters(query, self.config.filter_config)

        # 2. Detect intents
        intents = detect_intents(
            query,
            self.config.intent_keywords,
            self.config.substring_intents,
        )

        # 3. Query rewriting
        embed_text = cleaned_q or query
        query_expanded = None
        if self._rewriter:
            expanded = self._rewriter.rewrite(embed_text)
            if expanded:
                embed_text = expanded
                query_expanded = expanded

        # 4. Embed
        embedding = embed_query(embed_text, self.config)

        # 5. Build VS filter from extracted + extra
        vs_filter = build_vs_filter_dict(
            filters_extracted, self.config.filter_column_mapping
        )
        if extra_filters:
            if vs_filter:
                vs_filter = {"AND": [vs_filter, extra_filters]}
            else:
                vs_filter = extra_filters

        # 6. Vector Search
        rows = query_vector_search(embedding, self.config, top_k, vs_filter)
        total_candidates = len(rows)

        # 7. Re-rank
        results = rerank_results(rows, query, self.config, intents, top_k, score_fn)

        retrieval_ms = int((time.time() - t0) * 1000)

        return {
            "results": results,
            "filters_extracted": filters_extracted,
            "intents": intents,
            "query_expanded": query_expanded,
            "total_candidates": total_candidates,
            "retrieval_ms": retrieval_ms,
        }
