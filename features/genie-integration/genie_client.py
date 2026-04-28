"""
Configurable Genie client for Databricks Genie spaces.

Provides space detection, conversation management, and result extraction
without any hardcoded space IDs or keyword lists.

Usage:
    spaces = {
        "sales": SpaceConfig(
            space_id="your-space-id",
            keywords=["revenue", "orders", "product mix"],
            description="Revenue and order analytics",
        ),
        "marketing": SpaceConfig(
            space_id="another-space-id",
            keywords=["campaign", "roi", "channel"],
            description="Campaign and attribution analytics",
        ),
    }
    client = GenieClient(host="https://your-workspace.databricks.net", spaces=spaces)
    result = await client.ask("Show me total revenue by month", token="...")
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration dataclasses
# ---------------------------------------------------------------------------

@dataclass
class SpaceConfig:
    """Configuration for a single Genie space."""

    space_id: str
    keywords: list[str]
    description: str = ""


@dataclass
class GenieResult:
    """Structured result from a Genie query."""

    space_key: str
    space_name: str
    response_text: str = ""
    sql_query: Optional[str] = None
    columns: Optional[List[str]] = None
    rows: Optional[List[List[Any]]] = None
    conversation_id: Optional[str] = None
    execution_time_ms: float = 0.0
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        return self.error is None

    @property
    def row_count(self) -> int:
        return len(self.rows) if self.rows else 0


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class GenieClient:
    """
    Configurable client for Databricks Genie spaces.

    All space IDs, keywords, and tuning parameters are passed at init time.
    No hardcoded values.

    Args:
        host: Databricks workspace hostname (e.g. "https://my-workspace.cloud.databricks.net")
        spaces: Mapping of space_key -> SpaceConfig
        default_space: Key to use when no keyword match is found (must exist in *spaces*)
        timeout: Maximum seconds to wait for Genie to complete (default 60)
        poll_interval: Seconds between status checks (default 1.5)
        max_rows: Maximum data rows to include in results (default 25)
    """

    def __init__(
        self,
        host: str,
        spaces: dict[str, SpaceConfig],
        default_space: Optional[str] = None,
        timeout: float = 60.0,
        poll_interval: float = 1.5,
        max_rows: int = 25,
    ):
        if not spaces:
            raise ValueError("At least one SpaceConfig must be provided")

        self.host = host.rstrip("/")
        self.spaces = spaces
        self.default_space = default_space or next(iter(spaces))
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.max_rows = max_rows

        if self.default_space not in self.spaces:
            raise ValueError(
                f"default_space '{self.default_space}' not found in spaces dict"
            )

    # ------------------------------------------------------------------
    # Space detection
    # ------------------------------------------------------------------

    def detect_space(self, question: str) -> str:
        """
        Detect which Genie space should handle a question based on keywords.

        Iterates through all spaces in insertion order, returning the first
        space whose keyword list contains a match. Falls back to *default_space*.

        Args:
            question: Natural-language user question.

        Returns:
            Space key string (e.g. "sales", "marketing").
        """
        question_lower = question.lower()

        for space_key, space_config in self.spaces.items():
            for keyword in space_config.keywords:
                if keyword in question_lower:
                    logger.debug(
                        "Matched keyword %r -> space %r", keyword, space_key
                    )
                    return space_key

        logger.debug("No keyword match, defaulting to %r", self.default_space)
        return self.default_space

    def detect_space_with_scores(
        self, question: str, skip_spaces: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Score all spaces against a question and return ranked matches.

        Useful for fallback routing: if the top space fails, try the next.

        Args:
            question: Natural-language user question.
            skip_spaces: Space keys to exclude (e.g. previously failed).

        Returns:
            List of dicts sorted by score descending:
            [{"space_key": str, "score": int, "space_id": str}, ...]
        """
        question_lower = question.lower()
        skip = set(skip_spaces or [])
        scored = []

        for space_key, config in self.spaces.items():
            if space_key in skip:
                continue
            score = sum(1 for kw in config.keywords if kw in question_lower)
            scored.append({
                "space_key": space_key,
                "score": score,
                "space_id": config.space_id,
            })

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored

    # ------------------------------------------------------------------
    # Query execution
    # ------------------------------------------------------------------

    async def ask(
        self,
        question: str,
        token: str,
        space_id: Optional[str] = None,
        *,
        obo_client: Optional[Any] = None,
    ) -> GenieResult:
        """
        Send a question to a Genie space and poll until completion.

        Either *obo_client* (a Databricks SDK WorkspaceClient with OBO auth)
        or *token* (a raw bearer token for REST calls) must be provided.

        If *space_id* is not supplied, the client auto-detects the best space
        from the question text.

        Args:
            question: Natural-language analytics question.
            token: Databricks bearer token (used when obo_client is None).
            space_id: Explicit space ID override.
            obo_client: Optional Databricks WorkspaceClient with OBO auth.

        Returns:
            GenieResult with data, SQL, and metadata.
        """
        start_time = time.time()

        # Resolve space
        if space_id:
            # Find key by space_id
            space_key = next(
                (k for k, v in self.spaces.items() if v.space_id == space_id),
                self.default_space,
            )
        else:
            space_key = self.detect_space(question)
            space_id = self.spaces[space_key].space_id

        space_name = self.spaces[space_key].description or space_key

        try:
            if obo_client:
                return await self._ask_via_sdk(
                    obo_client, question, space_id, space_key, space_name, start_time
                )
            else:
                return await self._ask_via_rest(
                    token, question, space_id, space_key, space_name, start_time
                )
        except Exception as exc:
            execution_time = (time.time() - start_time) * 1000
            logger.error("Genie query failed: %s", exc, exc_info=True)
            return GenieResult(
                space_key=space_key,
                space_name=space_name,
                execution_time_ms=execution_time,
                error=str(exc),
            )

    # ------------------------------------------------------------------
    # SDK-based execution (preferred — uses OBO WorkspaceClient)
    # ------------------------------------------------------------------

    async def _ask_via_sdk(
        self,
        obo_client: Any,
        question: str,
        space_id: str,
        space_key: str,
        space_name: str,
        start_time: float,
    ) -> GenieResult:
        """Execute a Genie query using the Databricks SDK client."""

        # Start conversation
        conversation = obo_client.genie.start_conversation(
            space_id=space_id,
            content=question,
        )
        conversation_id = conversation.conversation_id
        message_id = conversation.message_id

        logger.debug("Started Genie conversation: %s", conversation_id)

        # Poll for completion
        elapsed = 0.0
        result_message = None

        while elapsed < self.timeout:
            message = obo_client.genie.get_message(
                space_id=space_id,
                conversation_id=conversation_id,
                message_id=message_id,
            )

            status = getattr(message, "status", None)

            if status == "COMPLETED":
                result_message = message
                break

            if status == "FAILED":
                error_msg = getattr(message, "error", "Query execution failed")
                return GenieResult(
                    space_key=space_key,
                    space_name=space_name,
                    execution_time_ms=(time.time() - start_time) * 1000,
                    error=f"Genie query failed: {error_msg}",
                )

            await asyncio.sleep(self.poll_interval)
            elapsed += self.poll_interval

        # Timeout
        if result_message is None:
            return GenieResult(
                space_key=space_key,
                space_name=space_name,
                execution_time_ms=(time.time() - start_time) * 1000,
                error=f"Genie query timed out after {self.timeout}s",
            )

        # Extract result
        execution_time = (time.time() - start_time) * 1000
        return self._extract_result(
            result_message, space_key, space_name, conversation_id, execution_time
        )

    # ------------------------------------------------------------------
    # REST-based execution (fallback — uses bearer token directly)
    # ------------------------------------------------------------------

    async def _ask_via_rest(
        self,
        token: str,
        question: str,
        space_id: str,
        space_key: str,
        space_name: str,
        start_time: float,
    ) -> GenieResult:
        """Execute a Genie query using raw REST API calls."""
        import httpx

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        base_url = f"{self.host}/api/2.0/genie/spaces/{space_id}"

        async with httpx.AsyncClient(timeout=self.timeout + 10) as http:
            # Start conversation
            resp = await http.post(
                f"{base_url}/conversations",
                headers=headers,
                json={"content": question},
            )
            resp.raise_for_status()
            conv_data = resp.json()
            conversation_id = conv_data["conversation_id"]
            message_id = conv_data["message_id"]

            logger.debug("Started Genie conversation (REST): %s", conversation_id)

            # Poll for completion
            elapsed = 0.0
            while elapsed < self.timeout:
                poll_resp = await http.get(
                    f"{base_url}/conversations/{conversation_id}/messages/{message_id}",
                    headers=headers,
                )
                poll_resp.raise_for_status()
                msg_data = poll_resp.json()

                status = msg_data.get("status")

                if status == "COMPLETED":
                    execution_time = (time.time() - start_time) * 1000
                    return self._extract_result_from_dict(
                        msg_data, space_key, space_name, conversation_id, execution_time
                    )

                if status == "FAILED":
                    error_msg = msg_data.get("error", "Query execution failed")
                    return GenieResult(
                        space_key=space_key,
                        space_name=space_name,
                        execution_time_ms=(time.time() - start_time) * 1000,
                        error=f"Genie query failed: {error_msg}",
                    )

                await asyncio.sleep(self.poll_interval)
                elapsed += self.poll_interval

        return GenieResult(
            space_key=space_key,
            space_name=space_name,
            execution_time_ms=(time.time() - start_time) * 1000,
            error=f"Genie query timed out after {self.timeout}s",
        )

    # ------------------------------------------------------------------
    # Result extraction helpers
    # ------------------------------------------------------------------

    def _extract_result(
        self,
        message: Any,
        space_key: str,
        space_name: str,
        conversation_id: str,
        execution_time_ms: float,
    ) -> GenieResult:
        """Extract structured result from an SDK Genie message object."""
        response_text = ""
        sql_query = None
        columns = None
        rows = None

        if hasattr(message, "attachments"):
            for attachment in message.attachments or []:
                # Text response
                if hasattr(attachment, "text") and attachment.text:
                    text_content = (
                        attachment.text.content
                        if hasattr(attachment.text, "content")
                        else str(attachment.text)
                    )
                    response_text += text_content + "\n"

                # SQL query and results
                if hasattr(attachment, "query"):
                    query_obj = attachment.query

                    if hasattr(query_obj, "query"):
                        sql_query = query_obj.query

                    if hasattr(query_obj, "result"):
                        result = query_obj.result
                        if hasattr(result, "columns"):
                            columns = [col.name for col in result.columns]
                        if hasattr(result, "data_array"):
                            rows = result.data_array[: self.max_rows]

        # Fallback: check for content attribute
        if not response_text and hasattr(message, "content"):
            response_text = str(message.content)

        return GenieResult(
            space_key=space_key,
            space_name=space_name,
            response_text=response_text.strip(),
            sql_query=sql_query,
            columns=columns,
            rows=rows,
            conversation_id=conversation_id,
            execution_time_ms=execution_time_ms,
        )

    def _extract_result_from_dict(
        self,
        msg_data: dict,
        space_key: str,
        space_name: str,
        conversation_id: str,
        execution_time_ms: float,
    ) -> GenieResult:
        """Extract structured result from a REST API JSON response."""
        response_text = ""
        sql_query = None
        columns = None
        rows = None

        for attachment in msg_data.get("attachments", []):
            if "text" in attachment:
                text_obj = attachment["text"]
                response_text += (
                    text_obj.get("content", str(text_obj)) + "\n"
                )

            if "query" in attachment:
                query_obj = attachment["query"]
                sql_query = query_obj.get("query")

                result_obj = query_obj.get("result", {})
                if "columns" in result_obj:
                    columns = [c.get("name", "") for c in result_obj["columns"]]
                if "data_array" in result_obj:
                    rows = result_obj["data_array"][: self.max_rows]

        if not response_text:
            response_text = msg_data.get("content", "")

        return GenieResult(
            space_key=space_key,
            space_name=space_name,
            response_text=response_text.strip(),
            sql_query=sql_query,
            columns=columns,
            rows=rows,
            conversation_id=conversation_id,
            execution_time_ms=execution_time_ms,
        )

    # ------------------------------------------------------------------
    # Routing helper
    # ------------------------------------------------------------------

    def should_route_to_genie(self, question: str) -> tuple[bool, str]:
        """
        Determine whether a question has analytics intent and which space fits.

        Returns:
            (should_route, space_key) -- should_route is True when the
            question contains analytics-style language.
        """
        question_lower = question.lower()

        analytics_indicators = [
            "show me", "how many", "total", "average", "count", "top",
            "by month", "by quarter", "by year", "trend", "compare",
        ]

        # Also check all configured space keywords
        all_keywords = []
        for config in self.spaces.values():
            all_keywords.extend(config.keywords)

        has_analytics_intent = any(
            ind in question_lower for ind in analytics_indicators
        )
        has_keyword_match = any(kw in question_lower for kw in all_keywords)

        if has_analytics_intent or has_keyword_match:
            space = self.detect_space(question)
            return True, space

        return False, ""
