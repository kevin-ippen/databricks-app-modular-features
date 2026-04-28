"""
Query decomposition for multi-query RAG retrieval.

Breaks complex user queries into multiple structured sub-queries
with keyword extraction and metadata filters, using an LLM.
"""

import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ── Filter operators ──────────────────────────────────────────────────────────

class FilterOperator(Enum):
    """SQL-style filter operators for VS metadata filtering."""
    EQUALS = "="
    NOT_EQUALS = "!="
    GREATER_THAN = ">"
    GREATER_THAN_OR_EQUAL = ">="
    LESS_THAN = "<"
    LESS_THAN_OR_EQUAL = "<="
    IN = "IN"
    NOT_IN = "NOT IN"
    LIKE = "LIKE"
    NOT_LIKE = "NOT LIKE"
    IS_NULL = "IS NULL"
    IS_NOT_NULL = "IS NOT NULL"


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class FilterClause:
    """A single filter condition for metadata filtering."""
    column: str
    operator: FilterOperator
    value: Any

    def to_sql(self) -> tuple[str, list]:
        """Convert to parameterized SQL WHERE clause fragment.

        Returns:
            (sql_fragment, params) — use with parameterized queries to prevent SQL injection.
            Example: cursor.execute(f"SELECT * FROM t WHERE {sql}", params)
        """
        op = self.operator

        if op == FilterOperator.IN:
            vals = self.value if isinstance(self.value, list) else [self.value]
            placeholders = ", ".join(["%s"] * len(vals))
            return f"{self.column} IN ({placeholders})", vals
        elif op == FilterOperator.NOT_IN:
            vals = self.value if isinstance(self.value, list) else [self.value]
            placeholders = ", ".join(["%s"] * len(vals))
            return f"{self.column} NOT IN ({placeholders})", vals
        elif op == FilterOperator.LIKE:
            return f"{self.column} LIKE %s", [f"%{self.value}%"]
        elif op == FilterOperator.NOT_LIKE:
            return f"{self.column} NOT LIKE %s", [f"%{self.value}%"]
        elif op == FilterOperator.IS_NULL:
            return f"{self.column} IS NULL", []
        elif op == FilterOperator.IS_NOT_NULL:
            return f"{self.column} IS NOT NULL", []
        else:
            return f"{self.column} {op.value} %s", [self.value]

    def to_dict(self) -> dict[str, Any]:
        return {"column": self.column, "operator": self.operator.value, "value": self.value}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FilterClause":
        return cls(column=data["column"], operator=FilterOperator(data["operator"]), value=data["value"])


@dataclass
class StructuredQuery:
    """A structured query with keywords and metadata filters."""
    keywords: list[str]
    filters: list[FilterClause] = field(default_factory=list)
    query_intent: str = ""
    weight: float = 1.0

    def get_search_text(self) -> str:
        """Get combined text for semantic search."""
        return " ".join(self.keywords)

    def get_filter_sql(self) -> Optional[tuple[str, list]]:
        """Generate parameterized SQL WHERE clause from filters (without 'WHERE').

        Returns:
            (sql_fragment, params) or None if no filters.
        """
        if not self.filters:
            return None
        fragments, all_params = [], []
        for f in self.filters:
            sql, params = f.to_sql()
            fragments.append(sql)
            all_params.extend(params)
        return " AND ".join(fragments), all_params

    def to_dict(self) -> dict[str, Any]:
        return {
            "keywords": self.keywords,
            "filters": [f.to_dict() for f in self.filters],
            "query_intent": self.query_intent,
            "weight": self.weight,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StructuredQuery":
        filters = [FilterClause.from_dict(f) for f in data.get("filters", [])]
        return cls(
            keywords=data["keywords"],
            filters=filters,
            query_intent=data.get("query_intent", ""),
            weight=data.get("weight", 1.0),
        )


# ── Decomposition prompt ─────────────────────────────────────────────────────

DECOMPOSITION_PROMPT = """You are a query decomposition expert for a Retrieval-Augmented Generation system.

Your task is to analyze a user query and break it into one or more structured queries
that can be executed against a vector search index with metadata filtering.

{spec_context}

---

## User Query
"{user_query}"

---

## Task

Decompose this query into structured queries. For each query:

1. **Keywords**: Extract semantic search terms (the core concepts to search for)
2. **Filters**: Apply metadata filters based on the index schema
3. **Intent**: Briefly describe what this query seeks

### Multi-Query Guidelines

Generate MULTIPLE queries when:
- The question has multiple aspects (e.g., "compare A and B" -> 2 queries)
- The question asks for both definition AND examples
- The question spans multiple topics

Generate a SINGLE query when:
- The question is focused on one topic
- The question is a simple "what is" or "how to" question

---

## Output Format

Respond with ONLY valid JSON (no markdown code blocks, no explanation):

{{
  "structured_queries": [
    {{
      "keywords": ["keyword1", "keyword2", "keyword3"],
      "filters": [
        {{"column": "column_name", "operator": "=", "value": "value"}}
      ],
      "query_intent": "Brief description of what this query seeks",
      "weight": 1.0
    }}
  ],
  "decomposition_reasoning": "Brief explanation of why you decomposed this way"
}}
"""


# ── JSON parsing with repair ─────────────────────────────────────────────────

def parse_json_response(content: str) -> Optional[dict[str, Any]]:
    """
    Parse JSON from LLM response, handling various formats.

    Tries: direct parse, ```json blocks, generic ``` blocks, raw extraction.
    """
    # Direct parse
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    # JSON code block
    if "```json" in content:
        try:
            start = content.find("```json") + 7
            end = content.find("```", start)
            return json.loads(content[start:end].strip())
        except (json.JSONDecodeError, ValueError):
            pass

    # Generic code block
    if "```" in content:
        try:
            start = content.find("```") + 3
            newline = content.find("\n", start)
            if newline > start:
                start = newline + 1
            end = content.find("```", start)
            return json.loads(content[start:end].strip())
        except (json.JSONDecodeError, ValueError):
            pass

    # Raw JSON object extraction
    try:
        json_start = content.find("{")
        json_end = content.rfind("}") + 1
        if json_start >= 0 and json_end > json_start:
            return json.loads(content[json_start:json_end])
    except json.JSONDecodeError:
        pass

    return None


# ── Decompose function ────────────────────────────────────────────────────────

async def decompose_query(
    user_query: str,
    llm_client: Any,
    spec_context: str = "",
    filterable_columns: Optional[list[str]] = None,
    max_queries: int = 3,
) -> list[StructuredQuery]:
    """
    Decompose user query into structured queries using LLM.

    Args:
        user_query: Natural language query from user.
        llm_client: Async-callable LLM client. Must support
                     `await llm_client.ainvoke(prompt)` returning
                     an object with `.content` attribute, OR be an
                     async function returning a string.
        spec_context: Context about the index schema and domain
                      (replaces the old SystemSpec dependency).
        filterable_columns: List of column names that accept filters.
                            Used to validate LLM-generated filters.
        max_queries: Maximum number of structured queries to generate.

    Returns:
        List of StructuredQuery objects.
    """
    prompt = DECOMPOSITION_PROMPT.format(
        spec_context=spec_context or "No specific schema context provided.",
        user_query=user_query,
    )

    try:
        # Call LLM
        response = await llm_client.ainvoke(prompt)
        content = response.content.strip() if hasattr(response, "content") else str(response).strip()

        parsed = parse_json_response(content)
        if not parsed or "structured_queries" not in parsed:
            logger.warning("Failed to parse decomposition response, using fallback")
            return [_create_fallback_query(user_query)]

        queries = []
        for sq_data in parsed.get("structured_queries", [])[:max_queries]:
            try:
                filters = []
                for f in sq_data.get("filters", []):
                    col = f.get("column", "")
                    if filterable_columns is None or col in filterable_columns:
                        filters.append(FilterClause(
                            column=col,
                            operator=FilterOperator(f["operator"]),
                            value=f["value"],
                        ))
                    else:
                        logger.warning(f"Skipping invalid filter column: {col}")

                queries.append(StructuredQuery(
                    keywords=sq_data.get("keywords", user_query.split()),
                    filters=filters,
                    query_intent=sq_data.get("query_intent", ""),
                    weight=sq_data.get("weight", 1.0),
                ))
            except Exception as e:
                logger.warning(f"Failed to parse structured query: {e}")
                continue

        if not queries:
            return [_create_fallback_query(user_query)]

        logger.info(f"Decomposed query into {len(queries)} structured queries")
        return queries

    except Exception as e:
        logger.error(f"Query decomposition failed: {e}")
        return [_create_fallback_query(user_query)]


def decompose_query_sync(
    user_query: str,
    llm_client: Any,
    spec_context: str = "",
    filterable_columns: Optional[list[str]] = None,
    max_queries: int = 3,
) -> list[StructuredQuery]:
    """Synchronous wrapper for decompose_query."""
    import asyncio
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(
        decompose_query(user_query, llm_client, spec_context, filterable_columns, max_queries)
    )


def _create_fallback_query(user_query: str) -> StructuredQuery:
    """Create a basic fallback query when decomposition fails."""
    stop_words = {"what", "is", "the", "how", "do", "i", "a", "an", "to", "for", "of", "and", "or"}
    keywords = [w for w in user_query.lower().split() if w not in stop_words and len(w) > 2]
    if not keywords:
        keywords = user_query.split()[:5]
    return StructuredQuery(
        keywords=keywords,
        filters=[],
        query_intent="Fallback query - direct keyword search",
        weight=1.0,
    )
