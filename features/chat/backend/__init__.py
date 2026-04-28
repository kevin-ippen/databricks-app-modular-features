"""
Chat Feature — Backend

SSE streaming chat router with generic chat handler support.
"""
from .events import EventType
from .router import (
    create_chat_router,
    ChatMessage,
    StreamChatRequest,
    ChatQueryRequest,
    ChatQueryResponse,
    SuggestionsResponse,
    ChatHandler,
    FollowupGenerator,
    UserIdExtractor,
)

__all__ = [
    "EventType",
    "create_chat_router",
    "ChatMessage",
    "StreamChatRequest",
    "ChatQueryRequest",
    "ChatQueryResponse",
    "SuggestionsResponse",
    "ChatHandler",
    "FollowupGenerator",
    "UserIdExtractor",
]
