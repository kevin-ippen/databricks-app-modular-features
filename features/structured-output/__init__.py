"""
structured-output feature -- LLM-powered structured JSON generation with Pydantic validation.

Public API:
    generate_structured_output  -- async function: prompt + Pydantic model -> validated instance
    extract_json_block          -- extract JSON from raw LLM text (strips fences, locates payload)
    build_retry_messages        -- append error context for LLM retry conversations
"""

from .client import generate_structured_output
from .extractors import build_retry_messages, extract_json_block

__all__ = [
    "generate_structured_output",
    "extract_json_block",
    "build_retry_messages",
]
