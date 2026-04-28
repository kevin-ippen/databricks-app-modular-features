"""
Message feedback API routes.

Provides endpoints for collecting and querying user feedback (thumbs up/down)
on AI-generated messages. Requires a ``FeedbackService`` instance and uses
``foundation.auth`` for user identity.

Usage:
    from features.message_feedback import create_feedback_router, FeedbackService

    service = FeedbackService(connection_factory=get_conn, table="app.message_feedback")
    app.include_router(create_feedback_router(service), prefix="/api")
"""

import logging
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from foundation.auth import get_user_email

from .service import FeedbackService

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Request / Response models
# --------------------------------------------------------------------------- #

class FeedbackRequest(BaseModel):
    """Request body for submitting message feedback."""
    message_id: str
    reaction_type: Literal["positive", "negative"]
    conversation_id: Optional[str] = None


class FeedbackResponse(BaseModel):
    """Response after feedback submission."""
    success: bool
    message: str


# --------------------------------------------------------------------------- #
# Router factory
# --------------------------------------------------------------------------- #

def create_feedback_router(service: FeedbackService) -> APIRouter:
    """Create a feedback router bound to the given ``FeedbackService``.

    Args:
        service: A configured ``FeedbackService`` instance.

    Returns:
        A FastAPI ``APIRouter`` with feedback endpoints.
    """
    router = APIRouter(prefix="/feedback", tags=["feedback"])

    @router.post("", response_model=FeedbackResponse)
    async def submit_feedback(request: Request, body: FeedbackRequest):
        """Submit feedback (thumbs up/down) for a message.

        The user is identified from the OBO token headers via
        ``foundation.auth.get_user_email``.
        """
        try:
            user_email = get_user_email(request)
            if not user_email:
                user_email = "anonymous"

            success = await service.store_feedback(
                message_id=body.message_id,
                user_id=user_email,
                reaction_type=body.reaction_type,
                conversation_id=body.conversation_id,
            )

            if success:
                return FeedbackResponse(
                    success=True,
                    message="Thanks for your feedback!",
                )
            return FeedbackResponse(
                success=False,
                message="Failed to save feedback. Please try again.",
            )

        except Exception as exc:
            logger.error("Feedback submission error: %s", exc, exc_info=True)
            raise HTTPException(
                status_code=500,
                detail=f"Failed to submit feedback: {exc}",
            )

    @router.get("/conversation/{conversation_id}")
    async def get_conversation_feedback(conversation_id: str):
        """Get aggregated feedback for a conversation."""
        try:
            return await service.get_feedback_for_conversation(conversation_id)
        except Exception as exc:
            logger.error("Conversation feedback error: %s", exc, exc_info=True)
            raise HTTPException(
                status_code=500,
                detail=f"Failed to get conversation feedback: {exc}",
            )

    @router.get("/stats")
    async def get_stats():
        """Get overall feedback statistics."""
        try:
            return await service.get_feedback_stats()
        except Exception as exc:
            logger.error("Feedback stats error: %s", exc, exc_info=True)
            raise HTTPException(
                status_code=500,
                detail=f"Failed to get feedback stats: {exc}",
            )

    return router
