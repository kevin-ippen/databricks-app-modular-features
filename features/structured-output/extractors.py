"""
JSON extraction and retry helpers for structured LLM output.

These utilities are intentionally stateless -- they operate on raw strings and
message lists so they can be composed with any LLM client or transport layer.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Type, TypeVar

from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


def extract_json_block(text: str) -> str:
    """Extract the first JSON object or array from raw LLM output.

    Handles:
      - Raw JSON with no wrapper
      - JSON inside ````` ``` ````` or ````` ```json ````` markdown fences
      - Leading/trailing prose around the JSON payload

    Returns
    -------
    str
        The extracted JSON string (not yet parsed).

    Raises
    ------
    ValueError
        If no JSON object or array can be located.
    """
    text = text.strip()

    # Strip markdown code fences
    if text.startswith("```"):
        first_nl = text.find("\n")
        if first_nl > 0:
            text = text[first_nl + 1:]
        else:
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    # Fast path: already starts with { or [
    if text and text[0] in "{[":
        return text

    # Locate first { or [ and corresponding last } or ]
    obj_start = text.find("{")
    arr_start = text.find("[")

    if obj_start == -1 and arr_start == -1:
        raise ValueError("No JSON object or array found in text")

    # Pick whichever appears first
    if obj_start == -1:
        start, open_char, close_char = arr_start, "[", "]"
    elif arr_start == -1:
        start, open_char, close_char = obj_start, "{", "}"
    elif obj_start <= arr_start:
        start, open_char, close_char = obj_start, "{", "}"
    else:
        start, open_char, close_char = arr_start, "[", "]"

    # Find matching close from the end
    end = text.rfind(close_char)
    if end == -1 or end <= start:
        raise ValueError(f"No matching '{close_char}' found for '{open_char}'")

    return text[start : end + 1]


def build_retry_messages(
    messages: list[dict[str, str]],
    assistant_content: str,
    error: str,
) -> list[dict[str, str]]:
    """Append the failed assistant response and a corrective user message.

    Returns a **new** list (does not mutate the input).
    """
    return [
        *messages,
        {"role": "assistant", "content": assistant_content},
        {
            "role": "user",
            "content": (
                f"The JSON you returned is invalid: {error}\n"
                "Please fix the errors and return ONLY valid JSON matching the schema."
            ),
        },
    ]
