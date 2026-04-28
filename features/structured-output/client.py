"""
Structured output generation via LLM with Pydantic validation.

Accepts any ``AsyncOpenAI``-compatible client (Databricks FMAPI, OpenAI, etc.)
and a Pydantic ``BaseModel`` subclass.  The JSON schema is embedded in the
system prompt, and on parse/validation failure the conversation is extended
with error context for automatic retry.

Usage:
    from openai import AsyncOpenAI
    from pydantic import BaseModel

    class MovieReview(BaseModel):
        title: str
        sentiment: str
        score: float

    client = AsyncOpenAI(base_url="...", api_key="...")
    review = await generate_structured_output(
        client=client,
        model="databricks-claude-haiku-4-5",
        prompt="Summarize the review: 'Great film, 9/10'",
        response_model=MovieReview,
    )
"""

from __future__ import annotations

import json
import logging
from typing import Type, TypeVar

from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError

from .extractors import build_retry_messages, extract_json_block

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


async def generate_structured_output(
    client: AsyncOpenAI,
    model: str,
    prompt: str,
    response_model: Type[T],
    *,
    max_retries: int = 2,
    temperature: float = 0.3,
    max_tokens: int = 4000,
    system_preamble: str = "",
) -> T:
    """Generate and validate structured JSON output from an LLM.

    Parameters
    ----------
    client : AsyncOpenAI
        An async OpenAI-compatible client (Databricks FMAPI, OpenAI, etc.).
    model : str
        Model / serving-endpoint name.
    prompt : str
        The user prompt describing what to generate.
    response_model : Type[T]
        A Pydantic ``BaseModel`` subclass.  Its JSON schema is embedded in
        the system prompt so the model knows the required structure.
    max_retries : int
        Number of additional attempts after the first failure (default 2).
    temperature : float
        Sampling temperature (default 0.3).
    max_tokens : int
        Maximum tokens for the LLM response.
    system_preamble : str
        Optional extra text prepended to the system prompt (e.g. domain
        context).  Leave empty for the default behaviour.

    Returns
    -------
    T
        The validated Pydantic model instance.

    Raises
    ------
    ValueError
        If all attempts fail to produce valid, schema-conforming JSON.
    """
    schema_json = json.dumps(response_model.model_json_schema(), indent=2)

    system_prompt = _build_system_prompt(schema_json, system_preamble)

    messages: list[dict[str, str]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
    ]

    last_error: str | None = None
    raw_content: str = ""

    for attempt in range(1, max_retries + 2):  # 1-indexed, inclusive of initial try
        try:
            logger.info("Structured output attempt %d/%d", attempt, max_retries + 1)

            response = await client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )

            raw_content = (response.choices[0].message.content or "").strip()

            # Extract and parse JSON
            json_str = extract_json_block(raw_content)
            result = response_model.model_validate_json(json_str)

            logger.info("Structured output succeeded on attempt %d", attempt)
            return result

        except (json.JSONDecodeError, ValueError) as exc:
            last_error = f"JSON extraction/parse error: {exc}"
            logger.warning("Attempt %d failed: %s", attempt, last_error)

        except ValidationError as exc:
            last_error = f"Schema validation error: {exc}"
            logger.warning("Attempt %d failed: %s", attempt, last_error)

        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            logger.warning("Attempt %d failed: %s", attempt, last_error)

        # Build retry messages for next attempt (if any)
        if attempt <= max_retries:
            messages = build_retry_messages(messages, raw_content, last_error or "unknown error")

    raise ValueError(
        f"Failed to generate valid structured output after {max_retries + 1} attempts. "
        f"Last error: {last_error}"
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_system_prompt(schema_json: str, preamble: str) -> str:
    """Assemble the system prompt with embedded JSON schema."""
    parts = []
    if preamble:
        parts.append(preamble.strip())
        parts.append("")  # blank line separator

    parts.append(
        "You are a helpful assistant that generates structured JSON output.\n"
        "You MUST respond with valid JSON that matches this exact schema:\n\n"
        f"{schema_json}\n\n"
        "Important:\n"
        "- Return ONLY valid JSON, no markdown formatting or explanation\n"
        "- Ensure all required fields are present\n"
        "- Follow the field descriptions exactly\n"
        "- Use realistic, grounded content -- do not fabricate specific metrics"
    )
    return "\n".join(parts)
