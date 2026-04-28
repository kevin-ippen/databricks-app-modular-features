"""LLM client — Databricks FMAPI (OpenAI-compatible) or Anthropic fallback.

In Databricks Apps: uses the workspace serving endpoint via WorkspaceClient.
Locally: falls back to the Anthropic SDK if ANTHROPIC_API_KEY is set.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# Model name mapping: config names → Databricks FMAPI endpoint names
_FMAPI_MODEL_MAP = {
    "claude-sonnet-4-20250514": "databricks-claude-sonnet-4",
    "claude-haiku-4-20250414": "databricks-claude-haiku-4-5",
    "claude-opus-4-20250514": "databricks-claude-opus-4-5",
    # Pass through any name that already starts with "databricks-"
}


def _resolve_model(model: str) -> str:
    """Map an Anthropic model name to a Databricks FMAPI endpoint name."""
    if model.startswith("databricks-"):
        return model
    return _FMAPI_MODEL_MAP.get(model, "databricks-claude-sonnet-4")


@dataclass
class LLMResponse:
    """Unified response from either FMAPI or Anthropic."""
    text: str
    input_tokens: int
    output_tokens: int


def _use_fmapi() -> bool:
    """Return True if running inside Databricks (use FMAPI)."""
    return bool(os.environ.get("DATABRICKS_HOST"))


def chat(
    model: str,
    messages: list[dict],
    max_tokens: int = 1000,
    temperature: float = 0.3,
) -> LLMResponse:
    """
    Send a chat completion request.

    Uses Databricks FMAPI when DATABRICKS_HOST is set,
    otherwise falls back to the Anthropic SDK.
    """
    if _use_fmapi():
        return _chat_fmapi(model, messages, max_tokens, temperature)
    return _chat_anthropic(model, messages, max_tokens, temperature)


def _chat_fmapi(
    model: str,
    messages: list[dict],
    max_tokens: int,
    temperature: float,
) -> LLMResponse:
    """Call Databricks FMAPI via OpenAI-compatible SDK."""
    from openai import OpenAI
    from databricks.sdk import WorkspaceClient

    wc = WorkspaceClient()
    host = wc.config.host
    token = wc.config.authenticate()["Authorization"].split(" ", 1)[1]

    client = OpenAI(
        base_url=f"{host}/serving-endpoints",
        api_key=token,
    )

    fmapi_model = _resolve_model(model)

    response = client.chat.completions.create(
        model=fmapi_model,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
    )

    choice = response.choices[0]
    usage = response.usage

    return LLMResponse(
        text=choice.message.content.strip(),
        input_tokens=usage.prompt_tokens,
        output_tokens=usage.completion_tokens,
    )


def _chat_anthropic(
    model: str,
    messages: list[dict],
    max_tokens: int,
    temperature: float,
) -> LLMResponse:
    """Call Anthropic API directly (local dev)."""
    import anthropic

    client = anthropic.Anthropic()
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        messages=messages,
    )

    return LLMResponse(
        text=response.content[0].text.strip(),
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
    )
