"""
Semantic search orchestration pipeline.

Coordinates the full search flow:
    extract filters -> detect intents -> rewrite query -> embed ->
    Vector Search -> optional enrichment -> multi-signal re-rank

All configuration (endpoints, indexes, models, weights) is injected via
SearchConfig — no hardcoded workspace hosts, catalog names, or index names.
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Callable, Optional, Awaitable, Union

import numpy as np
import requests

from .filters import FilterRegistry, extract_filters, build_vs_filter_dict
from .intents import IntentConfig, detect_intents, get_intent_boost_fields
from .rewriter import QueryRewriter

logger = logging.getLogger(__name__)


# ── Configuration ─────────────────────────────────────────────────────────────

@dataclass
class SearchConfig:
    """
    All configuration for the semantic search pipeline.

    Every workspace-specific value is injected here. Nothing is hardcoded.

    Args:
        vs_endpoint: Vector Search endpoint name.
        vs_index: Fully-qualified VS index name (catalog.schema.index).
        embedding_model: Serving endpoint name for the embedding model.
        token_provider: Callable returning a bearer token (sync or async).
        host: Databricks workspace URL (e.g., https://xxx.cloud.databricks.com).
        ranking_weights: Dict of signal_name -> weight for the re-ranking formula.
                         Keys: vs_score, quality_score, intent_bonus, secondary_score.
        rewrite_model: Optional serving endpoint name for query rewriting.
        rewrite_prompt: Optional system prompt for the rewriter.
        filter_registry: FilterRegistry for NL filter extraction.
        intent_configs: List of IntentConfig for intent detection.
        vs_columns: Columns to retrieve from Vector Search.
        overfetch_factor: Multiply top_k by this for VS query, then re-rank.
        default_limit: Default number of results returned.
        max_results: Hard cap on results.
        enrich_fn: Optional callable to enrich VS rows with additional data.
                   Signature: (rows: list[dict]) -> list[dict]
        score_fn: Optional custom scoring function per row.
                  Signature: (row, query, intents, weights) -> float
    """
    vs_endpoint: str
    vs_index: str
    embedding_model: str
    token_provider: Union[Callable[[], str], Callable[[], Awaitable[str]]]
    host: str

    ranking_weights: dict[str, float] = field(default_factory=lambda: {
        "vs_score": 0.50,
        "quality_score": 0.25,
        "intent_bonus": 0.15,
        "secondary_score": 0.10,
    })

    rewrite_model: Optional[str] = None
    rewrite_prompt: Optional[str] = None

    filter_registry: Optional[FilterRegistry] = None
    intent_configs: Optional[list[IntentConfig]] = None

    vs_columns: list[str] = field(default_factory=lambda: [
        "doc_id", "content", "title", "url",
    ])

    overfetch_factor: int = 3
    default_limit: int = 10
    max_results: int = 20

    enrich_fn: Optional[Callable[[list[dict]], list[dict]]] = None
    score_fn: Optional[Callable[[dict, str, dict[str, float], dict[str, float]], float]] = None

    def __post_init__(self):
        self.host = self.host.rstrip("/")


# ── Embedding ─────────────────────────────────────────────────────────────────

def embed_query(text: str, config: SearchConfig) -> list[float]:
    """
    Embed a single query string via the configured embedding endpoint.

    Returns a normalized float list (unit vector).
    """
    token = config.token_provider()
    if asyncio.iscoroutine(token):
        raise RuntimeError(
            "embed_query() is sync-only; use aembed_query() with async token providers"
        )
    resp = requests.post(
        f"{config.host}/serving-endpoints/{config.embedding_model}/invocations",
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


async def aembed_query(text: str, config: SearchConfig) -> list[float]:
    """Async variant of embed_query. Uses httpx if available, else threadpool."""
    token = config.token_provider()
    if asyncio.iscoroutine(token):
        token = await token

    try:
        import httpx
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{config.host}/serving-endpoints/{config.embedding_model}/invocations",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json={"input": [text]},
            )
            resp.raise_for_status()
            data = resp.json()["data"]
    except ImportError:
        loop = asyncio.get_running_loop()
        data = await loop.run_in_executor(
            None, _sync_embed, config.host, config.embedding_model, token, text,
        )

    emb = np.array(data[0]["embedding"], dtype=np.float32)
    norm = np.linalg.norm(emb)
    if norm > 0:
        emb = emb / norm
    return emb.tolist()


def _sync_embed(host: str, model: str, token: str, text: str) -> list[dict]:
    """Sync embedding call for async fallback."""
    resp = requests.post(
        f"{host}/serving-endpoints/{model}/invocations",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json={"input": [text]},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["data"]


# ── Vector Search query ───────────────────────────────────────────────────────

def query_vector_search(
    embedding: list[float],
    config: SearchConfig,
    top_k: int,
    vs_filter: Optional[dict] = None,
) -> list[dict]:
    """
    Query a Databricks Vector Search index (sync).

    Returns list of result dicts with columns from config.vs_columns + score.
    Gracefully returns [] if the index is not found (404).
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
        f"{config.host}/api/2.0/vector-search/indexes/{config.vs_index}/query",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json=body,
        timeout=30,
    )

    if resp.status_code == 404:
        logger.warning("VS index %s not found -- returning empty results", config.vs_index)
        return []

    resp.raise_for_status()
    return _parse_vs_response(resp.json())


async def aquery_vector_search(
    embedding: list[float],
    config: SearchConfig,
    top_k: int,
    vs_filter: Optional[dict] = None,
) -> list[dict]:
    """Async variant of query_vector_search."""
    body: dict[str, Any] = {
        "query_vector": embedding,
        "columns": config.vs_columns,
        "num_results": top_k * config.overfetch_factor,
    }
    if vs_filter:
        body["filters_json"] = json.dumps(vs_filter)

    token = config.token_provider()
    if asyncio.iscoroutine(token):
        token = await token

    try:
        import httpx
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{config.host}/api/2.0/vector-search/indexes/{config.vs_index}/query",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
            if resp.status_code == 404:
                logger.warning("VS index %s not found -- returning empty results", config.vs_index)
                return []
            resp.raise_for_status()
            return _parse_vs_response(resp.json())
    except ImportError:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, query_vector_search, embedding, config, top_k, vs_filter,
        )


def _parse_vs_response(result: dict) -> list[dict]:
    """Parse Databricks VS response format into list of flat dicts."""
    manifest = result.get("manifest", {})
    columns = [c.get("name") for c in manifest.get("columns", [])]
    data_array = result.get("result", {}).get("data_array", [])
    return [dict(zip(columns, row)) for row in data_array]


# ── Re-ranking ────────────────────────────────────────────────────────────────

def rerank_results(
    rows: list[dict],
    query: str,
    config: SearchConfig,
    intents: dict[str, float],
    top_k: int,
) -> list[dict]:
    """
    Multi-signal re-ranking of Vector Search results.

    Default formula:
        final = w1*vs_score + w2*quality_score + w3*intent_bonus + w4*secondary_score

    If config.score_fn is provided, it overrides the default formula entirely.
    Each row gets a ``final_rank_score`` field added.

    Args:
        rows: Raw VS results (must have a ``score`` field from VS).
        query: Original user query.
        config: SearchConfig with ranking_weights and optional score_fn.
        intents: Detected intent signals from detect_intents().
        top_k: Number of results to return after re-ranking.

    Returns:
        Top-k rows sorted by final_rank_score descending. Each row dict
        has ``final_rank_score`` added.
    """
    weights = config.ranking_weights
    intent_fields = get_intent_boost_fields(intents, config.intent_configs)

    ranked = []
    for row in rows:
        vs_score = float(row.get("score", 0) or 0)

        if config.score_fn:
            final_score = config.score_fn(row, query, intents, weights)
        else:
            # Default multi-signal formula
            quality_raw = float(row.get("quality_score", 0) or row.get("composite_score", 0) or 0)
            # Normalize quality to 0-1 (assumes 0-100 scale; clamp to be safe)
            quality_norm = min(quality_raw / 100.0, 1.0) if quality_raw > 1.0 else quality_raw

            secondary_raw = float(row.get("secondary_score", 0) or 0)

            # Intent bonus: sum intent-specific per-row boosts
            intent_bonus = 0.0
            for intent_name, boost_weight in intents.items():
                field_name = intent_fields.get(intent_name, "")
                if field_name:
                    field_val = float(row.get(field_name, 0) or 0)
                    # Normalize: if >1.0, assume 0-100 scale
                    if field_val > 1.0:
                        field_val = min(field_val / 100.0, 1.0)
                    intent_bonus += field_val * boost_weight
                else:
                    # No per-row field; flat boost
                    intent_bonus += 0.1 * boost_weight

            final_score = (
                weights.get("vs_score", 0.50) * vs_score
                + weights.get("quality_score", 0.25) * quality_norm
                + weights.get("intent_bonus", 0.15) * min(intent_bonus, 1.0)
                + weights.get("secondary_score", 0.10) * secondary_raw
            )

        row["final_rank_score"] = round(final_score, 4)
        ranked.append(row)

    ranked.sort(key=lambda r: r.get("final_rank_score", 0), reverse=True)
    return ranked[:top_k]


# ── High-level pipeline ──────────────────────────────────────────────────────

class SemanticSearchPipeline:
    """
    End-to-end semantic search pipeline.

    Orchestrates: extract filters -> detect intents -> rewrite query ->
    embed -> VS query -> optional enrichment -> multi-signal re-rank.

    Provides both sync ``search()`` and async ``asearch()`` interfaces,
    plus an SSE streaming variant ``search_stream()``.
    """

    def __init__(self, config: SearchConfig):
        self.config = config
        self._rewriter: Optional[QueryRewriter] = None

        if config.rewrite_model:
            self._rewriter = QueryRewriter(
                workspace_host=config.host,
                model_name=config.rewrite_model,
                token_provider=config.token_provider,
                system_prompt=config.rewrite_prompt,
            )

    # ── Sync search ───────────────────────────────────────────────────────

    def search(
        self,
        query: str,
        top_k: Optional[int] = None,
        extra_filters: Optional[dict] = None,
    ) -> dict[str, Any]:
        """
        Execute a full search pipeline (sync).

        Returns dict with keys:
            results, filters_extracted, intents, query_expanded,
            total_candidates, retrieval_ms
        """
        t0 = time.time()
        top_k = min(top_k or self.config.default_limit, self.config.max_results)

        # 1. Extract NL filters
        filters_extracted, cleaned_q = extract_filters(
            query, self.config.filter_registry,
        )

        # 2. Detect intents
        intents = detect_intents(query, self.config.intent_configs)

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

        # 5. Build VS filter
        vs_filter = build_vs_filter_dict(filters_extracted, self.config.filter_registry)
        if extra_filters:
            if vs_filter:
                vs_filter = {"AND": [vs_filter, extra_filters]}
            else:
                vs_filter = extra_filters

        # 6. Vector Search
        rows = query_vector_search(embedding, self.config, top_k, vs_filter)
        total_candidates = len(rows)

        # 7. Optional enrichment
        if self.config.enrich_fn and rows:
            rows = self.config.enrich_fn(rows)

        # 8. Re-rank
        results = rerank_results(rows, query, self.config, intents, top_k)

        retrieval_ms = int((time.time() - t0) * 1000)

        return {
            "results": results,
            "filters_extracted": filters_extracted,
            "intents": intents,
            "query_expanded": query_expanded,
            "total_candidates": total_candidates,
            "retrieval_ms": retrieval_ms,
        }

    # ── Async search ──────────────────────────────────────────────────────

    async def asearch(
        self,
        query: str,
        top_k: Optional[int] = None,
        extra_filters: Optional[dict] = None,
    ) -> dict[str, Any]:
        """
        Execute a full search pipeline (async).

        Same return format as search().
        """
        t0 = time.time()
        top_k = min(top_k or self.config.default_limit, self.config.max_results)

        # 1. Extract NL filters
        filters_extracted, cleaned_q = extract_filters(
            query, self.config.filter_registry,
        )

        # 2. Detect intents
        intents = detect_intents(query, self.config.intent_configs)

        # 3. Query rewriting (async)
        embed_text = cleaned_q or query
        query_expanded = None
        if self._rewriter:
            expanded = await self._rewriter.arewrite(embed_text)
            if expanded:
                embed_text = expanded
                query_expanded = expanded

        # 4. Embed (async)
        embedding = await aembed_query(embed_text, self.config)

        # 5. Build VS filter
        vs_filter = build_vs_filter_dict(filters_extracted, self.config.filter_registry)
        if extra_filters:
            if vs_filter:
                vs_filter = {"AND": [vs_filter, extra_filters]}
            else:
                vs_filter = extra_filters

        # 6. Vector Search (async)
        rows = await aquery_vector_search(embedding, self.config, top_k, vs_filter)
        total_candidates = len(rows)

        # 7. Optional enrichment (run in executor if sync)
        if self.config.enrich_fn and rows:
            loop = asyncio.get_running_loop()
            rows = await loop.run_in_executor(None, self.config.enrich_fn, rows)

        # 8. Re-rank
        results = rerank_results(rows, query, self.config, intents, top_k)

        retrieval_ms = int((time.time() - t0) * 1000)

        return {
            "results": results,
            "filters_extracted": filters_extracted,
            "intents": intents,
            "query_expanded": query_expanded,
            "total_candidates": total_candidates,
            "retrieval_ms": retrieval_ms,
        }

    # ── SSE streaming search ──────────────────────────────────────────────

    async def search_stream(
        self,
        query: str,
        top_k: Optional[int] = None,
        extra_filters: Optional[dict] = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """
        Streaming SSE variant of asearch.

        Yields status event dicts as the pipeline progresses:
            {"type": "status", "message": "..."}
            {"type": "parsed_filters", "data": {...}}
            {"type": "status", "message": "Searching with expanded understanding..."}
            {"type": "results", "data": [...], "total_candidates": N}
            {"type": "done", "retrieval_ms": N}
            {"type": "error", "message": "..."} (on failure)
        """
        t0 = time.time()
        top_k = min(top_k or self.config.default_limit, self.config.max_results)

        yield {"type": "status", "message": "Searching..."}

        try:
            # 1. Extract NL filters
            filters_extracted, cleaned_q = extract_filters(
                query, self.config.filter_registry,
            )
            if filters_extracted:
                yield {"type": "parsed_filters", "data": filters_extracted}

            # 2. Detect intents
            intents = detect_intents(query, self.config.intent_configs)

            # 3. Query rewriting
            embed_text = cleaned_q or query
            if self._rewriter:
                expanded = await self._rewriter.arewrite(embed_text)
                if expanded:
                    embed_text = expanded
                    yield {"type": "status", "message": "Searching with expanded understanding..."}

            # 4. Embed
            embedding = await aembed_query(embed_text, self.config)

            # 5. Build VS filter
            vs_filter = build_vs_filter_dict(filters_extracted, self.config.filter_registry)
            if extra_filters:
                if vs_filter:
                    vs_filter = {"AND": [vs_filter, extra_filters]}
                else:
                    vs_filter = extra_filters

            # 6. Vector Search
            rows = await aquery_vector_search(embedding, self.config, top_k, vs_filter)
            total_candidates = len(rows)

            # 7. Optional enrichment
            if self.config.enrich_fn and rows:
                loop = asyncio.get_running_loop()
                rows = await loop.run_in_executor(None, self.config.enrich_fn, rows)

            # 8. Re-rank
            results = rerank_results(rows, query, self.config, intents, top_k)

            retrieval_ms = int((time.time() - t0) * 1000)

            yield {
                "type": "results",
                "data": results,
                "total_candidates": total_candidates,
            }

            yield {"type": "done", "retrieval_ms": retrieval_ms}

        except Exception as e:
            logger.exception("search_stream error")
            yield {"type": "error", "message": str(e)}
