"""
Chat Streaming Router

Generic SSE streaming chat endpoint. Accepts an async generator as the chat
handler, making it domain-agnostic. Works with any LLM provider or agent
framework that yields SSE-compatible event dicts.

Usage:
    from features.chat.backend.router import create_chat_router

    async def my_chat_handler(messages, session_id, user_id):
        # Your agent/LLM logic here — yield event dicts
        yield {"type": "text.delta", "delta": "Hello"}
        yield {"type": "text.delta", "delta": " world!"}

    router = create_chat_router(
        chat_handler=my_chat_handler,
        followup_generator=my_followup_fn,  # optional
    )
    app.include_router(router)
"""

import json
import logging
from typing import AsyncGenerator, Awaitable, Callable, Dict, List, Optional

from pydantic import BaseModel
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from .events import EventType

logger = logging.getLogger(__name__)


# =============================================================================
# Request / Response Models
# =============================================================================

class ChatMessage(BaseModel):
    """Single chat message."""
    role: str  # "user" or "assistant"
    content: str | List[dict]  # String for text, list for multimodal
    timestamp: Optional[int] = None


class StreamChatRequest(BaseModel):
    """Request for streaming chat."""
    messages: List[ChatMessage]
    session_id: Optional[str] = None


class ChatQueryRequest(BaseModel):
    """Request for non-streaming chat."""
    message: str
    conversation_id: Optional[str] = None


class ChatQueryResponse(BaseModel):
    """Response for non-streaming chat."""
    message: str
    conversation_id: str
    suggestions: Optional[List[str]] = None


class SuggestionsResponse(BaseModel):
    """Response with starter suggestions."""
    suggestions: List[str]


# =============================================================================
# Type aliases for handler callables
# =============================================================================

# chat_handler(messages, session_id, user_id) -> async generator of event dicts
ChatHandler = Callable[
    [List[Dict], Optional[str], str],
    AsyncGenerator[Dict, None],
]

# followup_generator(request, user_question, assistant_response, agent_used) -> list of strings
FollowupGenerator = Callable[
    [Request, str, str, Optional[str]],
    Awaitable[List[str]],
]

# user_id_extractor(request) -> str
UserIdExtractor = Callable[[Request], str]


# =============================================================================
# Default implementations
# =============================================================================

def _default_user_id_extractor(request: Request) -> str:
    """Best-effort user ID extraction from OBO token claims."""
    import base64 as _b64

    try:
        auth_header = request.headers.get("authorization", "")
        if not auth_header.startswith("Bearer "):
            return "anonymous"
        token = auth_header[7:]
        parts = token.split(".")
        if len(parts) >= 2:
            padded = parts[1] + "=="
            payload = json.loads(_b64.b64decode(padded).decode("utf-8", errors="ignore"))
            return payload.get("sub") or payload.get("email") or "anonymous"
    except Exception:
        pass
    return "anonymous"


def _default_followup_suggestions(
    user_message: str,
    agent_used: Optional[str] = None,
) -> List[str]:
    """Rule-based fallback follow-up suggestions."""
    message_lower = user_message.lower()

    # Agent-specific suggestions
    if agent_used:
        agent_lower = agent_used.lower()
        if agent_lower == "genie":
            return [
                "Can you visualize this data?",
                "Break this down by time period",
                "What other tables have related data?",
            ]
        elif agent_lower == "rag":
            return [
                "What are the key takeaways?",
                "How does this compare to industry standards?",
                "Can you give me a practical example?",
            ]
        elif agent_lower == "websearch":
            return [
                "What are the implications of this?",
                "Find more recent updates on this",
                "How does this affect our industry?",
            ]
        elif agent_lower == "general":
            return [
                "Can you elaborate on that?",
                "How would I apply this in practice?",
                "What are the alternatives?",
            ]

    # Keyword-based fallback
    if any(kw in message_lower for kw in ["sql", "query", "table", "data", "schema", "revenue", "sales", "customer"]):
        return [
            "Can you visualize this data?",
            "Break this down by segment",
            "What other metrics should I look at?",
        ]

    if any(kw in message_lower for kw in ["chart", "visualization", "graph", "plot"]):
        return [
            "Change this to a different chart type",
            "Add a trend line",
            "Export this data to CSV",
        ]

    if any(kw in message_lower for kw in ["document", "pdf", "file", "explain"]):
        return [
            "What are the practical implications?",
            "How does this compare to alternatives?",
            "Give me a real-world example",
        ]

    if any(kw in message_lower for kw in ["news", "latest", "recent", "search", "trend"]):
        return [
            "What are the key implications?",
            "How might this affect our business?",
            "Find related developments",
        ]

    # Default suggestions
    return [
        "Tell me more about this",
        "How can I use this information?",
        "What should I look at next?",
    ]


async def _default_llm_followup_generator(
    request: Request,
    user_question: str,
    assistant_response: str,
    agent_used: Optional[str] = None,
) -> List[str]:
    """
    Generate contextual follow-up suggestions using an LLM.

    Override this with your own implementation that calls your preferred
    LLM provider. This default returns an empty list, falling back to
    rule-based suggestions.
    """
    return []


# =============================================================================
# Router factory
# =============================================================================

def create_chat_router(
    chat_handler: ChatHandler,
    followup_generator: Optional[FollowupGenerator] = None,
    user_id_extractor: Optional[UserIdExtractor] = None,
    fallback_suggestions_fn: Optional[Callable] = None,
    starter_suggestions: Optional[List[str]] = None,
    prefix: str = "/chat",
    tags: Optional[List[str]] = None,
) -> APIRouter:
    """
    Create a FastAPI router with SSE streaming chat endpoints.

    Args:
        chat_handler: Async generator function that yields SSE event dicts.
            Signature: (messages: List[Dict], session_id: Optional[str], user_id: str)
        followup_generator: Optional async function to generate LLM-based follow-ups.
            Signature: (request, user_question, assistant_response, agent_used) -> List[str]
        user_id_extractor: Optional function to extract user ID from request.
            Defaults to JWT claim extraction from Authorization header.
        fallback_suggestions_fn: Optional function for rule-based fallback follow-ups.
            Signature: (user_message, agent_used) -> List[str]
        starter_suggestions: Optional list of starter suggestions for /suggestions endpoint.
        prefix: URL prefix for the router. Default: "/chat"
        tags: OpenAPI tags. Default: ["chat"]
    """
    router = APIRouter(prefix=prefix, tags=tags or ["chat"])

    _followup_gen = followup_generator or _default_llm_followup_generator
    _user_id_fn = user_id_extractor or _default_user_id_extractor
    _fallback_fn = fallback_suggestions_fn or _default_followup_suggestions
    _starters = starter_suggestions or [
        "What can you help me with?",
        "Show me some example queries",
        "Explain what tools you have access to",
    ]

    @router.post("/stream")
    async def stream_chat(
        request: Request,
        body: StreamChatRequest,
    ):
        """
        Stream chat responses as Server-Sent Events.

        Response: SSE stream with events:
        - data: {"type": "text.delta", "delta": "..."}
        - data: {"type": "tool.call", "name": "...", "args": {...}}
        - data: {"type": "tool.output", "name": "...", "output": "..."}
        - data: {"type": "thinking.step", "step_type": "routing", "agent": "...", "message": "..."}
        - data: {"type": "thinking.retry", "step_type": "routing", "agent": "...", "message": "..."}
        - data: {"type": "metadata", "data": {...}}
        - data: {"type": "followups", "suggestions": [...]}
        - data: {"type": "error", "message": "..."}
        - data: [DONE]
        """

        async def event_generator():
            accumulated_response = ""
            agent_used = None

            try:
                logger.info(f"[STREAM] Starting with {len(body.messages)} messages")

                messages = [
                    {"role": msg.role, "content": msg.content}
                    for msg in body.messages
                ]

                user_id = _user_id_fn(request)

                async for event in chat_handler(
                    messages,
                    body.session_id,
                    user_id,
                ):
                    yield f"data: {json.dumps(event)}\n\n"

                    # Track response content and agent for follow-up generation
                    if event.get("type") == EventType.TEXT_DELTA:
                        accumulated_response += event.get("delta", "")
                    elif event.get("type") == EventType.METADATA:
                        agent_used = event.get("data", {}).get("agent_used")

                # Generate contextual follow-up suggestions
                user_message = messages[-1]["content"] if messages else ""
                if isinstance(user_message, list):
                    user_message = next(
                        (p.get("text", "") for p in user_message if p.get("type") == "text"),
                        ""
                    )

                followups = []
                try:
                    followups = await _followup_gen(
                        request,
                        user_question=user_message,
                        assistant_response=accumulated_response[:1000],
                        agent_used=agent_used,
                    )
                    logger.info(f"[STREAM] LLM follow-ups: {followups}")
                except Exception as fe:
                    logger.warning(f"[STREAM] Follow-up generation failed: {fe}")

                if not followups:
                    followups = _fallback_fn(user_message, agent_used)
                    logger.info(f"[STREAM] Using fallback follow-ups: {followups}")

                yield f"data: {json.dumps({'type': EventType.FOLLOWUPS, 'suggestions': followups})}\n\n"
                yield "data: [DONE]\n\n"
                logger.info("[STREAM] Completed")

            except Exception as e:
                logger.error(f"[STREAM] Error: {e}", exc_info=True)
                error_event = {
                    "type": EventType.ERROR,
                    "message": f"Streaming failed: {str(e)}"
                }
                yield f"data: {json.dumps(error_event)}\n\n"

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @router.get("/suggestions", response_model=SuggestionsResponse)
    async def get_suggestions():
        """Get starter query suggestions."""
        return SuggestionsResponse(suggestions=_starters)

    return router
