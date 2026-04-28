"""
LLM-based query rewriting for semantic search.

Expands terse user queries into richer embedding text via a
configurable model endpoint (Databricks FMAPI or compatible).
"""

import logging
from typing import Optional, Callable

import requests

logger = logging.getLogger(__name__)


# ── Default system prompt ─────────────────────────────────────────────────────

DEFAULT_REWRITE_PROMPT = """You expand search queries for a semantic search engine.
Given a user query, return a single expanded version optimized for semantic embedding search.

Rules:
- Add synonyms and related terms
- Expand abbreviations
- Add contextual terms that relate to the query intent
- Keep the original intent -- don't add unrelated features
- Return ONLY the expanded query, no explanation, no quotes
- Max 60 words

Examples:
"budget friendly option" -> "affordable inexpensive value deal low cost economical budget-friendly option"
"quiet place for two" -> "quiet peaceful secluded private romantic retreat for two people couples getaway intimate setting"
"""


class QueryRewriter:
    """
    LLM-based query expansion for better embedding matches.

    Args:
        workspace_host: Databricks workspace URL (e.g., https://xxx.cloud.databricks.com).
        model_name: Serving endpoint name for the rewrite model.
        system_prompt: System prompt guiding the rewrite behavior.
        token_provider: Callable that returns a bearer token string.
        max_tokens: Maximum tokens for the rewrite response.
        temperature: LLM temperature (0 = deterministic).
        cache_size: Max entries in the in-memory cache.
        min_query_length: Queries shorter than this are not rewritten.
        timeout: HTTP request timeout in seconds.
    """

    def __init__(
        self,
        workspace_host: str,
        model_name: str,
        token_provider: Callable[[], str],
        system_prompt: Optional[str] = None,
        max_tokens: int = 80,
        temperature: float = 0,
        cache_size: int = 500,
        min_query_length: int = 5,
        timeout: int = 15,
    ):
        self.workspace_host = workspace_host.rstrip("/")
        self.model_name = model_name
        self.token_provider = token_provider
        self.system_prompt = system_prompt or DEFAULT_REWRITE_PROMPT
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.cache_size = cache_size
        self.min_query_length = min_query_length
        self.timeout = timeout
        self._cache: dict[str, str] = {}

    def rewrite(self, query: str) -> Optional[str]:
        """
        Expand a query via LLM for better embedding retrieval.

        Returns the expanded query string, or None if rewriting fails
        or is skipped (query too short, LLM error, etc.).
        """
        if len(query) < self.min_query_length:
            return None

        # Cache lookup
        cache_key = query.lower().strip()
        if cache_key in self._cache:
            return self._cache[cache_key]

        try:
            token = self.token_provider()
            payload = {
                "messages": [
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": query},
                ],
                "max_tokens": self.max_tokens,
                "temperature": self.temperature,
            }
            resp = requests.post(
                f"{self.workspace_host}/serving-endpoints/{self.model_name}/invocations",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            expanded = data["choices"][0]["message"]["content"].strip()

            if expanded and len(expanded) > len(query):
                # Cache with eviction
                self._cache[cache_key] = expanded
                if len(self._cache) > self.cache_size:
                    # Evict oldest entries (FIFO approximation)
                    keys_to_remove = list(self._cache.keys())[: self.cache_size // 5]
                    for k in keys_to_remove:
                        del self._cache[k]
                return expanded

        except Exception as e:
            logger.warning(f"Query rewrite failed: {e}")

        return None

    def clear_cache(self):
        """Clear the rewrite cache."""
        self._cache.clear()
