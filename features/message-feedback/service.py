"""
Message feedback data access layer.

Handles storage and retrieval of user reactions (thumbs up/down) for message
quality monitoring. Uses dependency injection for the database connection
factory and configurable table names.

Usage:
    from features.message_feedback import FeedbackService

    # With asyncpg-style connection factory
    service = FeedbackService(
        connection_factory=my_get_connection,
        table="my_schema.message_feedback",
    )
    await service.store_feedback("msg_1", "user@example.com", "positive")
"""

import logging
from datetime import datetime
from typing import Any, Callable, Coroutine, Dict, List, Optional

logger = logging.getLogger(__name__)

# Type alias: an async callable that returns an asyncpg-compatible connection
ConnectionFactory = Callable[[], Coroutine[Any, Any, Any]]

_DEFAULT_TABLE = "message_feedback"


class FeedbackService:
    """Async service for message feedback CRUD operations.

    Args:
        connection_factory: An async callable that returns a database connection
            with ``execute``, ``fetch``, and ``close`` methods (asyncpg API).
        table: Fully-qualified table name (e.g. ``"myapp.message_feedback"``).
            Defaults to ``"message_feedback"``.
    """

    def __init__(
        self,
        connection_factory: ConnectionFactory,
        table: str = _DEFAULT_TABLE,
    ) -> None:
        self._get_connection = connection_factory
        self._table = table

    # --------------------------------------------------------------------- #
    # Write
    # --------------------------------------------------------------------- #

    async def store_feedback(
        self,
        message_id: str,
        user_id: str,
        reaction_type: str,
        conversation_id: Optional[str] = None,
    ) -> bool:
        """Store or update user feedback for a message (upsert).

        Args:
            message_id: Unique message identifier.
            user_id: User who gave feedback.
            reaction_type: ``"positive"`` or ``"negative"``.
            conversation_id: Optional conversation thread ID.

        Returns:
            ``True`` if the write succeeded, ``False`` otherwise.
        """
        conn = await self._get_connection()
        try:
            await conn.execute(
                f"""
                INSERT INTO {self._table}
                    (message_id, user_id, conversation_id, reaction_type)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (message_id, user_id)
                DO UPDATE SET
                    reaction_type = EXCLUDED.reaction_type,
                    updated_at = CURRENT_TIMESTAMP
                """,
                message_id,
                user_id,
                conversation_id,
                reaction_type,
            )
            return True
        except Exception as exc:
            logger.error("Error storing feedback: %s", exc, exc_info=True)
            return False
        finally:
            await conn.close()

    # --------------------------------------------------------------------- #
    # Read
    # --------------------------------------------------------------------- #

    async def get_feedback_for_conversation(
        self, conversation_id: str
    ) -> Dict[str, Any]:
        """Get aggregated feedback summary for a conversation.

        Returns:
            ``{"positive": {"count": N, "unique_users": M}, "negative": {...}, "total_feedback": T}``
        """
        conn = await self._get_connection()
        try:
            rows = await conn.fetch(
                f"""
                SELECT
                    reaction_type,
                    COUNT(*) AS count,
                    COUNT(DISTINCT user_id) AS unique_users
                FROM {self._table}
                WHERE conversation_id = $1
                GROUP BY reaction_type
                """,
                conversation_id,
            )

            result: Dict[str, Any] = {
                "positive": {"count": 0, "unique_users": 0},
                "negative": {"count": 0, "unique_users": 0},
                "total_feedback": 0,
            }
            for row in rows:
                reaction = row["reaction_type"]
                result[reaction] = {
                    "count": row["count"],
                    "unique_users": row["unique_users"],
                }
                result["total_feedback"] += row["count"]
            return result

        except Exception as exc:
            logger.error("Error getting conversation feedback: %s", exc, exc_info=True)
            return {
                "positive": {"count": 0, "unique_users": 0},
                "negative": {"count": 0, "unique_users": 0},
                "total_feedback": 0,
            }
        finally:
            await conn.close()

    async def get_user_feedback_history(
        self, user_id: str, limit: int = 20
    ) -> List[Dict[str, Any]]:
        """Get a user's recent feedback history, newest first.

        Args:
            user_id: User identifier.
            limit: Max records to return (default 20).
        """
        conn = await self._get_connection()
        try:
            rows = await conn.fetch(
                f"""
                SELECT message_id, reaction_type, created_at, conversation_id
                FROM {self._table}
                WHERE user_id = $1
                ORDER BY created_at DESC
                LIMIT $2
                """,
                user_id,
                limit,
            )
            return [
                {
                    "message_id": row["message_id"],
                    "reaction_type": row["reaction_type"],
                    "created_at": row["created_at"],
                    "conversation_id": row["conversation_id"],
                }
                for row in rows
            ]
        except Exception as exc:
            logger.error("Error getting user feedback history: %s", exc, exc_info=True)
            return []
        finally:
            await conn.close()

    async def get_feedback_stats(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Get overall feedback statistics with optional date range.

        Returns:
            ``{"total_feedback": N, "positive_count": N, "negative_count": N,
              "positive_percentage": float, "by_date": [...]}``
        """
        conn = await self._get_connection()
        try:
            query = f"""
                SELECT
                    reaction_type,
                    COUNT(*) AS count,
                    COUNT(DISTINCT user_id) AS unique_users,
                    DATE(created_at) AS feedback_date
                FROM {self._table}
                WHERE 1=1
            """
            params: list = []

            if start_date:
                params.append(start_date)
                query += f" AND created_at >= ${len(params)}"
            if end_date:
                params.append(end_date)
                query += f" AND created_at <= ${len(params)}"

            query += " GROUP BY reaction_type, DATE(created_at) ORDER BY feedback_date DESC"

            rows = await conn.fetch(query, *params)

            total_positive = 0
            total_negative = 0
            by_date: Dict[str, Dict[str, Any]] = {}

            for row in rows:
                reaction = row["reaction_type"]
                count = row["count"]
                date_str = row["feedback_date"].isoformat()

                if reaction == "positive":
                    total_positive += count
                else:
                    total_negative += count

                if date_str not in by_date:
                    by_date[date_str] = {"date": date_str, "positive": 0, "negative": 0}
                by_date[date_str][reaction] = count

            total_feedback = total_positive + total_negative
            positive_pct = (
                (total_positive / total_feedback * 100) if total_feedback > 0 else 0
            )

            return {
                "total_feedback": total_feedback,
                "positive_count": total_positive,
                "negative_count": total_negative,
                "positive_percentage": round(positive_pct, 1),
                "by_date": sorted(
                    by_date.values(), key=lambda x: x["date"], reverse=True
                ),
            }

        except Exception as exc:
            logger.error("Error getting feedback stats: %s", exc, exc_info=True)
            return {
                "total_feedback": 0,
                "positive_count": 0,
                "negative_count": 0,
                "positive_percentage": 0.0,
                "by_date": [],
            }
        finally:
            await conn.close()
