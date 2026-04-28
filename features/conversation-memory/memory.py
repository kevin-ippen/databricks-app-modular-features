"""
Memory Layer -- Persistent conversation history and summarization.

Gives every agent path real context across turns and sessions:
- load_history_and_summary: inject last N turns + running summary into the LLM context
- save_turn: persist user + assistant messages after each response
- maybe_summarize: background LLM call every N messages to distill context

Database-agnostic: accepts a `connection_factory` async callable that returns
an asyncpg-compatible connection (or any object with `fetchrow`, `fetch`,
`execute`, `close` methods).

All parameters (history depth, truncation, summarization trigger, model,
prompt) are configurable via constructor arguments.
"""

import logging
import uuid
from typing import Awaitable, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class MemoryLayer:
    """
    Async conversation memory backed by any asyncpg-compatible database.

    Args:
        connection_factory: Async callable that returns a database connection.
            The connection must support: fetchrow, fetch, execute, close.
        history_depth: Number of recent messages to load. Default: 10.
        message_truncation: Max characters per message when saving. Default: 4000.
        summarization_trigger: Summarize every N messages. Default: 12.
        summary_model: LLM model name for summarization. Default: "databricks-claude-haiku-4-5".
        summary_prompt: System prompt for summarization. If None, uses a generic default.

    Usage:
        memory = MemoryLayer(connection_factory=get_async_connection)
        history, summary = await memory.load_history_and_summary(session_id)
        count = await memory.save_turn(session_id, user_id, user_msg, assistant_msg)
        await memory.maybe_summarize(session_id, count, llm_client)
    """

    def __init__(
        self,
        connection_factory: Callable[[], Awaitable],
        history_depth: int = 10,
        message_truncation: int = 4000,
        summarization_trigger: int = 12,
        summary_model: str = "databricks-claude-haiku-4-5",
        summary_prompt: Optional[str] = None,
    ):
        self._get_conn = connection_factory
        self._history_depth = history_depth
        self._message_truncation = message_truncation
        self._summarization_trigger = summarization_trigger
        self._summary_model = summary_model
        self._summary_prompt = summary_prompt or (
            "Summarize this conversation in 2-3 sentences. "
            "Focus on: what topics were discussed, key findings, and what the user "
            "seems most interested in. Be specific about details, metrics, and topics. "
            "This summary will be given to a future AI assistant as background context."
        )

    async def load_history_and_summary(
        self, session_id: str
    ) -> Tuple[List[Dict], str]:
        """
        Load recent turns and running summary for a session.

        Returns:
            (history, summary) where history is [{role, content}] oldest-first
            and summary is a plain string (empty if no summary yet)
        """
        try:
            conn = await self._get_conn()
            try:
                # Fetch summary
                row = await conn.fetchrow(
                    "SELECT summary FROM conversations WHERE session_id = $1",
                    session_id,
                )
                summary = row["summary"] if row and row["summary"] else ""

                # Fetch last N messages, oldest first
                rows = await conn.fetch(
                    """
                    SELECT role, content FROM messages
                    WHERE session_id = $1
                    ORDER BY created_at DESC
                    LIMIT $2
                    """,
                    session_id,
                    self._history_depth,
                )
            finally:
                await conn.close()

            # Reverse so oldest first (DESC + reverse = chronological)
            history = [
                {"role": r["role"], "content": r["content"]}
                for r in reversed(rows)
            ]
            return history, summary

        except Exception as e:
            logger.warning(
                f"[Memory] load failed for session {session_id}: {e}"
            )
            return [], ""

    async def save_turn(
        self,
        session_id: str,
        user_id: str,
        user_message: str,
        assistant_message: str,
    ) -> int:
        """
        Persist user + assistant messages and upsert conversation metadata.

        Returns:
            New total message count for this session (used for summarization trigger)
        """
        try:
            conn = await self._get_conn()
            try:
                # Upsert conversation row (creates if first turn)
                await conn.execute(
                    """
                    INSERT INTO conversations (session_id, user_id, message_count, updated_at)
                    VALUES ($1, $2, 2, CURRENT_TIMESTAMP)
                    ON CONFLICT (session_id) DO UPDATE
                    SET message_count = conversations.message_count + 2,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    session_id,
                    user_id,
                )

                # Insert user message
                await conn.execute(
                    """
                    INSERT INTO messages (message_id, session_id, role, content)
                    VALUES ($1, $2, 'user', $3)
                    """,
                    str(uuid.uuid4()),
                    session_id,
                    user_message[: self._message_truncation],
                )

                # Insert assistant message
                await conn.execute(
                    """
                    INSERT INTO messages (message_id, session_id, role, content)
                    VALUES ($1, $2, 'assistant', $3)
                    """,
                    str(uuid.uuid4()),
                    session_id,
                    assistant_message[: self._message_truncation],
                )

                # Return updated count
                row = await conn.fetchrow(
                    "SELECT message_count FROM conversations WHERE session_id = $1",
                    session_id,
                )
                return row["message_count"] if row else 2

            finally:
                await conn.close()

        except Exception as e:
            logger.warning(
                f"[Memory] save_turn failed for session {session_id}: {e}"
            )
            return 0

    async def maybe_summarize(
        self,
        session_id: str,
        message_count: int,
        async_openai_client,
        model: Optional[str] = None,
    ) -> None:
        """
        Generate a running summary every N messages.

        Uses the configured LLM to distill recent messages into a compact
        context string that's prepended to future LLM calls as background
        knowledge. Non-critical: failures are silently logged.

        Args:
            session_id: Conversation session ID.
            message_count: Current total message count.
            async_openai_client: OpenAI-compatible async client.
            model: Override the default summary model. Optional.
        """
        if message_count % self._summarization_trigger != 0:
            return

        try:
            conn = await self._get_conn()
            try:
                rows = await conn.fetch(
                    """
                    SELECT role, content FROM messages
                    WHERE session_id = $1
                    ORDER BY created_at DESC
                    LIMIT 20
                    """,
                    session_id,
                )
            finally:
                await conn.close()

            if not rows:
                return

            turns_text = "\n".join(
                f"{r['role'].upper()}: {r['content'][:300]}"
                for r in reversed(rows)
            )

            response = await async_openai_client.chat.completions.create(
                model=model or self._summary_model,
                messages=[
                    {
                        "role": "system",
                        "content": self._summary_prompt,
                    },
                    {"role": "user", "content": turns_text},
                ],
                max_tokens=200,
                temperature=0.3,
                stream=False,
            )

            summary = response.choices[0].message.content.strip()

            conn = await self._get_conn()
            try:
                await conn.execute(
                    "UPDATE conversations SET summary = $1 WHERE session_id = $2",
                    summary,
                    session_id,
                )
            finally:
                await conn.close()

            logger.info(
                f"[Memory] Summary updated for session {session_id[:16]}..."
            )

        except Exception as e:
            logger.warning(
                f"[Memory] summarize failed for session {session_id}: {e}"
            )
