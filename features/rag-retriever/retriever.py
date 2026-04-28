"""
RAG Retriever — standalone async class.

Multi-query decomposition -> Vector Search -> reranking -> grounded response.
No LangGraph / agent state dependencies.
"""

import logging
import time
from typing import Any, Optional, Callable

from .query_decomposer import StructuredQuery, decompose_query
from .citations import build_citation_list, format_citations, extract_citation_refs

logger = logging.getLogger(__name__)


# ── Response generation prompt ────────────────────────────────────────────────

DEFAULT_RESPONSE_PROMPT = """You are a knowledgeable assistant generating a response based on retrieved documents.

## Context
{spec_context}

## User Question
"{user_query}"

## Retrieved Documents
{retrieved_docs}

## Instructions

1. **Ground your response in the retrieved documents** - only include information that appears in the documents
2. **Cite your sources** using [1], [2], etc. references that map to the documents above
3. **Follow the response format**: {response_format}
4. **Keep response under {max_length} tokens**
5. **If documents don't contain relevant information**, acknowledge this honestly

Generate a helpful, grounded response:
"""


class RAGRetriever:
    """
    Standalone RAG retriever with multi-query decomposition.

    Usage:
        retriever = RAGRetriever(
            vs_query_fn=my_vector_search_function,
            llm_client=my_llm,
            spec_context="This is a knowledge base about ...",
        )
        result = await retriever.retrieve("What is X?")

    Args:
        vs_query_fn: Async function (query_text: str, filters_sql: str | None, top_k: int) -> list[dict].
                     Each dict should have at least: doc_id, content, score.
        llm_client: Async-callable LLM. Must support `await llm.ainvoke(prompt)`.
        spec_context: Description of the knowledge domain for the LLM.
        filterable_columns: Column names that accept metadata filters.
        default_top_k: Default number of results per sub-query.
        rerank_top_k: Number of results to keep after reranking.
        response_format: Instruction for LLM response format (e.g., "bullet points").
        max_response_length: Token limit hint for response generation.
        response_prompt: Custom response generation prompt template.
        id_field: Key name for doc ID in VS results.
        content_field: Key name for document content in VS results.
    """

    def __init__(
        self,
        vs_query_fn: Callable,
        llm_client: Any,
        spec_context: str = "",
        filterable_columns: Optional[list[str]] = None,
        default_top_k: int = 10,
        rerank_top_k: int = 5,
        response_format: str = "concise paragraphs with citations",
        max_response_length: int = 500,
        response_prompt: Optional[str] = None,
        id_field: str = "doc_id",
        content_field: str = "content",
    ):
        self.vs_query_fn = vs_query_fn
        self.llm_client = llm_client
        self.spec_context = spec_context
        self.filterable_columns = filterable_columns
        self.default_top_k = default_top_k
        self.rerank_top_k = rerank_top_k
        self.response_format = response_format
        self.max_response_length = max_response_length
        self.response_prompt = response_prompt or DEFAULT_RESPONSE_PROMPT
        self.id_field = id_field
        self.content_field = content_field

    async def retrieve(
        self,
        query: str,
        top_k: Optional[int] = None,
        generate_response: bool = True,
    ) -> dict[str, Any]:
        """
        Execute the full RAG pipeline.

        Args:
            query: User question.
            top_k: Override default_top_k for this request.
            generate_response: If True, generate a grounded LLM response.
                               If False, return only retrieved documents.

        Returns:
            Dict with keys:
                - query: original query
                - structured_queries: decomposed sub-queries
                - results: reranked document list
                - citations: citation metadata
                - response: generated text (if generate_response=True)
                - timing: timing breakdown dict
        """
        start_time = time.time()
        top_k = top_k or self.default_top_k

        # Step 1: Query decomposition
        decomp_start = time.time()
        structured_queries = await decompose_query(
            user_query=query,
            llm_client=self.llm_client,
            spec_context=self.spec_context,
            filterable_columns=self.filterable_columns,
            max_queries=3,
        )
        decomp_ms = (time.time() - decomp_start) * 1000

        # Step 2: Execute queries against Vector Search
        retrieval_start = time.time()
        all_results = []
        for sq in structured_queries:
            results = await self.vs_query_fn(
                query_text=sq.get_search_text(),
                filters_sql=sq.get_filter_sql(),
                top_k=top_k,
            )
            all_results.extend(results)

        # Deduplicate by doc_id
        unique = self._deduplicate(all_results)
        retrieval_ms = (time.time() - retrieval_start) * 1000

        # Step 3: Rerank (simple score-based for now)
        reranked = self._rerank(unique, self.rerank_top_k)

        # Step 4: Generate response
        response_text = ""
        citations = build_citation_list(reranked, id_field=self.id_field)
        generation_ms = 0.0

        if generate_response and reranked:
            gen_start = time.time()
            response_text, citations = await self._generate_response(query, reranked)
            generation_ms = (time.time() - gen_start) * 1000
        elif not reranked:
            response_text = (
                "I couldn't find relevant information in the knowledge base "
                "to answer your question. Please try rephrasing or ask about "
                "a different topic."
            )

        total_ms = (time.time() - start_time) * 1000

        return {
            "query": query,
            "structured_queries": [sq.to_dict() for sq in structured_queries],
            "results": reranked,
            "citations": citations,
            "response": response_text,
            "timing": {
                "decomposition_ms": round(decomp_ms),
                "retrieval_ms": round(retrieval_ms),
                "generation_ms": round(generation_ms),
                "total_ms": round(total_ms),
            },
        }

    def _deduplicate(self, results: list[dict]) -> list[dict]:
        """Deduplicate results by doc_id, keeping highest score."""
        seen: dict[str, dict] = {}
        for r in results:
            doc_id = r.get(self.id_field, "")
            if not doc_id:
                continue
            if doc_id not in seen or r.get("score", 0) > seen[doc_id].get("score", 0):
                seen[doc_id] = r
        return sorted(seen.values(), key=lambda x: x.get("score", 0), reverse=True)

    def _rerank(self, results: list[dict], top_k: int) -> list[dict]:
        """
        Rerank results. Currently score-based; extend for
        LLM-based or instruction-aware reranking.
        """
        return results[:top_k]

    async def _generate_response(
        self, query: str, results: list[dict]
    ) -> tuple[str, list[dict]]:
        """Generate a grounded response with citations."""
        docs_text = ""
        citations = []

        for i, r in enumerate(results, 1):
            content = r.get(self.content_field, "")[:500]
            doc_type = r.get("doc_type", "document")
            topic = r.get("topic", "")

            docs_text += f"\n[{i}] ({doc_type}{', ' + topic if topic else ''})\n{content}\n"
            citations.append({
                "ref": i,
                "doc_id": r.get(self.id_field, ""),
                "doc_uri": r.get("doc_uri", ""),
                "doc_type": doc_type,
                "topic": topic,
                "title": f"{doc_type.replace('_', ' ').title()}: {topic}" if topic else doc_type.replace('_', ' ').title(),
            })

        prompt = self.response_prompt.format(
            spec_context=self.spec_context,
            user_query=query,
            retrieved_docs=docs_text,
            response_format=self.response_format,
            max_length=self.max_response_length,
        )

        try:
            response = await self.llm_client.ainvoke(prompt)
            text = response.content.strip() if hasattr(response, "content") else str(response).strip()
            return text, citations
        except Exception as e:
            logger.error(f"Response generation error: {e}")
            if results:
                return f"Based on the retrieved documents: {results[0].get(self.content_field, '')[:300]}...", citations[:1]
            return "Unable to generate response.", []
