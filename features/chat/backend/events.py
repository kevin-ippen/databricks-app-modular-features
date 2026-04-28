"""SSE event type definitions for chat streaming."""
from enum import Enum


class EventType(str, Enum):
    TEXT_DELTA = "text.delta"
    TOOL_CALL = "tool.call"
    TOOL_OUTPUT = "tool.output"
    THINKING_STEP = "thinking.step"
    THINKING_RETRY = "thinking.retry"
    METADATA = "metadata"
    FOLLOWUPS = "followups"
    RESULT_ENVELOPE = "result.envelope"
    ERROR = "error"
