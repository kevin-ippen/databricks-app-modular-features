"""
LLM-based intent classification router.

Uses a few-shot prompt with structured JSON output to classify user
messages into agent intents. Falls back to "general" on any error.

All model names, valid agent lists, and system prompts are configurable.
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Route decision
# ---------------------------------------------------------------------------

@dataclass
class RouteDecision:
    """Structured routing decision from the LLM classifier."""

    agent: str
    """Target agent name."""

    confidence: float
    """Confidence score (0.0 - 1.0)."""

    reasoning: str
    """Human-readable explanation (shown in thinking section)."""

    entities: Dict
    """Extracted entities: {time_range, geo, metric, domain, ...}."""

    needs_compound: bool = False
    """True when the query needs multiple agents (e.g. internal + external)."""


# ---------------------------------------------------------------------------
# Default system prompt (few-shot)
# ---------------------------------------------------------------------------

_DEFAULT_SYSTEM_PROMPT = """\
You are a routing classifier for an analytics assistant.
Given a user message, output ONLY a JSON object with the routing decision.

## Available Agents
{agent_descriptions}

## Compound Queries
Set needs_compound=true ONLY when the query explicitly asks to compare internal data
against external benchmarks (e.g. "our CAC vs industry average").

## Output Format (strict JSON, no markdown)
{{
  "agent": "<agent_name>",
  "confidence": <0.0-1.0>,
  "reasoning": "<1 sentence explaining why>",
  "needs_compound": <true|false>,
  "entities": {{
    "time_range": "<e.g. last 4 weeks, Q1 2024>",
    "geo": "<region or store filter if mentioned>",
    "metric": "<primary metric being asked about>",
    "domain": "<e.g. delivery, revenue, customers>"
  }}
}}

## Few-Shot Examples
{few_shot_examples}
"""


# ---------------------------------------------------------------------------
# Router class
# ---------------------------------------------------------------------------

class LLMRouter:
    """
    Intent classification router backed by an LLM (e.g. Haiku 4.5).

    Single LLM call per request. Falls back to 'general' on any error.

    Args:
        model: Model name for the FMAPI / OpenAI-compatible endpoint.
        valid_agents: Set of allowed agent names. Any unknown agent in the
            LLM response falls back to ``fallback_agent``.
        fallback_agent: Agent returned when classification fails (default "general").
        system_prompt: Full system prompt. Use ``{agent_descriptions}`` and
            ``{few_shot_examples}`` placeholders for injection.
        agent_descriptions: Markdown block describing available agents.
        few_shot_examples: Markdown block with few-shot JSON examples.
        max_tokens: Max tokens for the classification response (default 300).
        temperature: Sampling temperature (default 0.0 for determinism).
    """

    def __init__(
        self,
        model: str = "databricks-claude-haiku-4-5",
        valid_agents: Optional[Set[str]] = None,
        fallback_agent: str = "general",
        system_prompt: Optional[str] = None,
        agent_descriptions: str = "",
        few_shot_examples: str = "",
        max_tokens: int = 300,
        temperature: float = 0.0,
    ):
        self.model = model
        self.valid_agents = valid_agents or {"general"}
        self.fallback_agent = fallback_agent
        self.max_tokens = max_tokens
        self.temperature = temperature

        # Build system prompt
        base = system_prompt or _DEFAULT_SYSTEM_PROMPT
        self.system_prompt = base.format(
            agent_descriptions=agent_descriptions,
            few_shot_examples=few_shot_examples,
        )

    async def classify(
        self,
        message: str,
        summary: str = "",
        last_turns: Optional[List[Dict]] = None,
        token: str = "",
        *,
        client: Optional[object] = None,
    ) -> RouteDecision:
        """
        Classify intent and return a RouteDecision.

        Provide either *client* (an async OpenAI-compatible client) or
        *token* (a Databricks bearer token -- the method will create a
        client via ``foundation.auth``).

        Args:
            message: Latest user message.
            summary: Running conversation summary (optional context).
            last_turns: Recent turns for context (optional).
            token: Databricks OBO token for FMAPI.
            client: Pre-built async OpenAI client (takes precedence over token).

        Returns:
            RouteDecision with agent, confidence, reasoning, entities.
        """
        try:
            if client is None:
                from foundation.auth import get_async_openai_client
                client = get_async_openai_client(token)

            # Build context from conversation history
            context_lines: list[str] = []
            if summary:
                context_lines.append(f"Conversation context: {summary}")
            if last_turns:
                for turn in last_turns[-2:]:
                    role = turn.get("role", "")
                    content = str(turn.get("content", ""))[:200]
                    context_lines.append(f"{role.upper()}: {content}")

            user_content = message
            if context_lines:
                user_content = "\n".join(context_lines) + f"\n\nNEW MESSAGE: {message}"

            response = await client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": user_content},
                ],
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                stream=False,
            )

            raw = response.choices[0].message.content.strip()

            # Strip markdown code fences if present
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]

            parsed = json.loads(raw)

            agent = parsed.get("agent", self.fallback_agent)
            if agent not in self.valid_agents:
                logger.warning(
                    "[Router] Unknown agent %r, falling back to %r",
                    agent,
                    self.fallback_agent,
                )
                agent = self.fallback_agent

            return RouteDecision(
                agent=agent,
                confidence=float(parsed.get("confidence", 0.5)),
                reasoning=parsed.get("reasoning", ""),
                entities=parsed.get("entities", {}),
                needs_compound=bool(parsed.get("needs_compound", False)),
            )

        except Exception as exc:
            logger.warning(
                "[Router] Classification failed (falling back to %s): %s",
                self.fallback_agent,
                exc,
            )
            return RouteDecision(
                agent=self.fallback_agent,
                confidence=0.5,
                reasoning=f"Router unavailable, defaulting to {self.fallback_agent}: {exc}",
                entities={},
                needs_compound=False,
            )
