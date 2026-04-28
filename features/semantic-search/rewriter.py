"""
LLM-based query rewriting for semantic search.

Expands terse user queries into richer embedding text via a configurable
model endpoint (Databricks FMAPI or compatible). Includes an LRU cache
for repeated queries, async support, and graceful degradation.
"""

import asyncio
import logging
from collections import OrderedDict
from typing import Optional, Callable, Awaitable, Union

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


class _LRUCache:
    """Simple LRU cache backed by OrderedDict."""

    def __init__(self, maxsize: int = 500):
        self._maxsize = maxsize
        self._data: OrderedDict[str, str] = OrderedDict()

    def get(self, key: str) -> Optional[str]:
        if key in self._data:
            self._data.move_to_end(key)
            return self._data[key]
        return None

    def put(self, key: str, value: str) -> None:
        if key in self._data:
            self._data.move_to_end(key)
        self._data[key] = value
        while len(self._data) > self._maxsize:
            self._data.popitem(last=False)

    def clear(self) -> None:
        self._data.clear()

    def __len__(self) -> int:
        return len(self._data)


class QueryRewriter:
    """
    LLM-based query expansion for better embedding matches.

    Features:
    - LRU cache (configurable max entries) avoids repeated LLM calls
    - Configurable system prompt via constructor
    - Graceful degradation: returns original query on any failure
    - Both sync ``rewrite()`` and async ``arewrite()`` interfaces

    Args:
        workspace_host: Databricks workspace URL (e.g., https://xxx.cloud.databricks.com).
        model_name: Serving endpoint name for the rewrite model.
        token_provider: Callable returning a bearer token string.
                        May be sync (``() -> str``) or async (``() -> Awaitable[str]``).
        system_prompt: System prompt guiding rewrite behavior.
        max_tokens: Maximum tokens for the rewrite response.
        temperature: LLM temperature (0 = deterministic).
        cache_maxsize: Max entries in the LRU cache.
        min_query_length: Queries shorter than this are not rewritten.
        timeout: HTTP request timeout in seconds.
    """

    def __init__(
        self,
        workspace_host: str,
        model_name: str,
        token_provider: Union[Callable[[], str], Callable[[], Awaitable[str]]],
        system_prompt: Optional[str] = None,
        max_tokens: int = 80,
        temperature: float = 0,
        cache_maxsize: int = 500,
        min_query_length: int = 5,
        timeout: int = 15,
    ):
        self.workspace_host = workspace_host.rstrip("/")
        self.model_name = model_name
        self.token_provider = token_provider
        self.system_prompt = system_prompt or DEFAULT_REWRITE_PROMPT
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.min_query_length = min_query_length
        self.timeout = timeout
        self._cache = _LRUCache(maxsize=cache_maxsize)

    def _build_payload(self, query: str) -> dict:
        return {
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": query},
            ],
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }

    def _endpoint_url(self) -> str:
        return f"{self.workspace_host}/serving-endpoints/{self.model_name}/invocations"

    @staticmethod
    def _extract_expanded(data: dict, original: str) -> Optional[str]:
        """Extract the expanded query from an FMAPI response, or None if invalid."""
        try:
            expanded = data["choices"][0]["message"]["content"].strip()
            if expanded and len(expanded) > len(original):
                return expanded
        except (KeyError, IndexError, TypeError):
            pass
        return None

    # ── Synchronous ───────────────────────────────────────────────────────

    def rewrite(self, query: str) -> Optional[str]:
        """
        Expand a query via LLM for better embedding retrieval (sync).

        Returns the expanded query string, or None if rewriting fails
        or is skipped (query too short, LLM error, etc.).
        Always safe to call -- never raises.
        """
        if len(query) < self.min_query_length:
            return None

        cache_key = query.lower().strip()
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            token = self.token_provider()
            # If token_provider is async, fall back to None
            if asyncio.iscoroutine(token):
                token.close()  # prevent unawaited coroutine warning
                logger.warning("Sync rewrite() called with async token_provider; skipping rewrite")
                return None

            resp = requests.post(
                self._endpoint_url(),
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json=self._build_payload(query),
                timeout=self.timeout,
            )
            resp.raise_for_status()
            expanded = self._extract_expanded(resp.json(), query)
            if expanded:
                self._cache.put(cache_key, expanded)
                return expanded

        except Exception as e:
            logger.warning("Query rewrite failed: %s", e)

        return None

    # ── Asynchronous ──────────────────────────────────────────────────────

    async def arewrite(self, query: str) -> Optional[str]:
        """
        Expand a query via LLM for better embedding retrieval (async).

        Uses httpx if available, otherwise falls back to sync in a thread.
        Returns the expanded query string, or None on any failure.
        Always safe to call -- never raises.
        """
        if len(query) < self.min_query_length:
            return None

        cache_key = query.lower().strip()
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            token = self.token_provider()
            if asyncio.iscoroutine(token):
                token = await token

            # Try httpx first (async-native), fall back to sync requests in threadpool
            try:
                import httpx
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.post(
                        self._endpoint_url(),
                        headers={
                            "Authorization": f"Bearer {token}",
                            "Content-Type": "application/json",
                        },
                        json=self._build_payload(query),
                    )
                    resp.raise_for_status()
                    data = resp.json()
            except ImportError:
                # Fallback: run sync request in executor
                loop = asyncio.get_running_loop()
                data = await loop.run_in_executor(
                    None, self._sync_request, token, query
                )

            expanded = self._extract_expanded(data, query)
            if expanded:
                self._cache.put(cache_key, expanded)
                return expanded

        except Exception as e:
            logger.warning("Async query rewrite failed: %s", e)

        return None

    def _sync_request(self, token: str, query: str) -> dict:
        """Sync HTTP call for use in async fallback path."""
        resp = requests.post(
            self._endpoint_url(),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json=self._build_payload(query),
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def clear_cache(self) -> None:
        """Clear the rewrite cache."""
        self._cache.clear()

    @property
    def cache_size(self) -> int:
        """Current number of cached rewrites."""
        return len(self._cache)
