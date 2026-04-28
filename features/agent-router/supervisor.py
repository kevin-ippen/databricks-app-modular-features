"""
Supervisor node for LangGraph multi-agent routing.

Provides heuristic keyword-based intent classification and routing.
All domain-specific keywords are injected via RoutingConfig -- nothing
is hardcoded.
"""

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from .state import AgentState


# ---------------------------------------------------------------------------
# Routing configuration
# ---------------------------------------------------------------------------

@dataclass
class RoutingConfig:
    """
    Configurable keyword lists for heuristic intent routing.

    Each list maps user-message keywords/phrases to an intent category.
    Supply domain-specific terms at init time; leave empty lists for
    intents you don't need.

    Attributes:
        sql_keywords: Phrases that indicate a data/analytics query
            (e.g. ["show me", "total", "average", "top 10"]).
        rag_keywords: Phrases that indicate a document/knowledge question
            (e.g. ["mmm", "attribution", "uploaded document"]).
        websearch_keywords: Phrases that indicate a need for real-time info
            (e.g. ["latest", "news", "today", "stock price"]).
        schema_explorer_phrases: Phrases that indicate data discovery
            (e.g. ["what tables", "describe table", "sample data"]).
        general_keywords: Phrases that indicate general knowledge
            (e.g. ["what is", "explain", "define"]).
        genie_space_keywords: Per-space keyword config for Genie routing.
            Maps space_key -> {"keywords": [...], "fallback_spaces": [...]}.
        sql_action_verbs: Verbs that signal analytics intent when combined
            with a metric term.
        sql_metrics: Metric terms that signal analytics intent when combined
            with an action verb.
        sql_patterns: Time/aggregation patterns that signal analytics intent.
    """

    sql_keywords: list[str] = field(default_factory=list)
    rag_keywords: list[str] = field(default_factory=list)
    websearch_keywords: list[str] = field(default_factory=list)
    schema_explorer_phrases: list[str] = field(default_factory=list)
    general_keywords: list[str] = field(default_factory=list)

    # Genie-specific: per-space keywords with fallback chains
    genie_space_keywords: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    # Compound analytics detection (action + metric + pattern)
    sql_action_verbs: list[str] = field(default_factory=list)
    sql_metrics: list[str] = field(default_factory=list)
    sql_patterns: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Default (empty) config
# ---------------------------------------------------------------------------

_EMPTY_CONFIG = RoutingConfig()


# ---------------------------------------------------------------------------
# Heuristic routing
# ---------------------------------------------------------------------------

def heuristic_routing(
    user_message: str,
    config: RoutingConfig,
    *,
    has_documents: bool = False,
    failed_agents: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Keyword-based intent routing.

    Priority order:
        1. Schema Explorer (data discovery)
        2. RAG (documents / methodology)
        3. WebSearch (current events / real-time)
        4. Genie / SQL (analytics queries)
        5. General (default)

    Supports retry: agents in *failed_agents* are skipped.

    Args:
        user_message: The user's question.
        config: RoutingConfig with keyword lists.
        has_documents: Whether user has uploaded files.
        failed_agents: Agents that already failed (to exclude).

    Returns:
        Dict with keys: agent, confidence, reason, and optionally
        genie_space, retrieval_spec, alternative_routes.
    """
    message_lower = user_message.lower()
    failed = set(failed_agents or [])

    def skip(agent: str) -> bool:
        return agent in failed

    # ----- 1. Schema Explorer -----
    if not skip("schema_explorer") and config.schema_explorer_phrases:
        if any(phrase in message_lower for phrase in config.schema_explorer_phrases):
            return {
                "agent": "schema_explorer",
                "confidence": 0.9,
                "reason": "Data discovery question - exploring tables/schema",
            }

    # ----- 2. RAG / knowledge retrieval -----
    if not skip("rag") and config.rag_keywords:
        if any(kw in message_lower for kw in config.rag_keywords):
            return {
                "agent": "rag",
                "confidence": 0.85,
                "reason": "Knowledge / document question",
            }
        # Document reference when user has files
        if has_documents and any(
            kw in message_lower for kw in ("document", "file", "uploaded", "pdf")
        ):
            return {
                "agent": "rag",
                "confidence": 0.85,
                "reason": "Question about uploaded documents",
            }

    # ----- 3. WebSearch -----
    if not skip("websearch") and config.websearch_keywords:
        if any(term in message_lower for term in config.websearch_keywords):
            return {
                "agent": "websearch",
                "confidence": 0.85,
                "reason": "Question requires current/real-time information",
            }

    # ----- 4. Genie / SQL (analytics) -----
    if not skip("genie") and not skip("sql"):
        result = _detect_genie_route(message_lower, config, failed)
        if result:
            return result

    # ----- 5. General (default) -----
    if not skip("general"):
        return {
            "agent": "general",
            "confidence": 0.7,
            "reason": "General knowledge question"
            + (" (fallback after failed agents)" if failed else ""),
        }

    # All exhausted
    return {
        "agent": "END",
        "confidence": 0.0,
        "reason": f"All suitable agents failed: {list(failed)}",
    }


def _detect_genie_route(
    message_lower: str,
    config: RoutingConfig,
    failed: set,
) -> Optional[Dict[str, Any]]:
    """
    Detect if the message should be routed to a Genie space.

    Returns routing dict or None if no analytics intent detected.
    """
    has_action = any(v in message_lower for v in config.sql_action_verbs)
    has_metric = any(m in message_lower for m in config.sql_metrics)
    has_pattern = any(p in message_lower for p in config.sql_patterns)

    if not ((has_action and (has_metric or has_pattern)) or (has_metric and has_pattern)):
        return None

    # Score each Genie space
    scored: list[tuple[str, int, list[str]]] = []
    for space_key, space_cfg in config.genie_space_keywords.items():
        if space_key in failed:
            continue
        kws = space_cfg.get("keywords", [])
        score = sum(1 for kw in kws if kw in message_lower)
        if score > 0:
            scored.append((space_key, score, space_cfg.get("fallback_spaces", [])))

    scored.sort(key=lambda x: x[1], reverse=True)

    if scored:
        primary = scored[0][0]
        fallbacks = scored[0][2]

        alternatives = []
        for fb in fallbacks:
            if fb not in failed:
                alternatives.append({
                    "agent": "genie",
                    "genie_space": fb,
                    "confidence": 0.7,
                    "reason": f"Fallback: Genie ({fb} space)",
                })
        for space_key, _score, _ in scored[1:3]:
            if space_key not in failed and not any(
                a.get("genie_space") == space_key for a in alternatives
            ):
                alternatives.append({
                    "agent": "genie",
                    "genie_space": space_key,
                    "confidence": 0.65,
                    "reason": f"Alternative: Genie ({space_key} space)",
                })

        return {
            "agent": "genie",
            "confidence": 0.85,
            "reason": f"Analytics query -> Genie ({primary} space)",
            "genie_space": primary,
            "alternative_routes": alternatives,
        }

    # No space keyword match -- pick first available
    available = [
        k
        for k in config.genie_space_keywords
        if k not in failed
    ]
    if available:
        return {
            "agent": "genie",
            "confidence": 0.75,
            "reason": f"Analytics query -> Genie ({available[0]} space, default)",
            "genie_space": available[0],
            "alternative_routes": [
                {"agent": "genie", "genie_space": s, "confidence": 0.6}
                for s in available[1:]
            ],
        }

    return None


# ---------------------------------------------------------------------------
# Supervisor node (LangGraph-compatible)
# ---------------------------------------------------------------------------

async def supervisor_node(
    state: AgentState,
    config: dict = None,
    *,
    routing_config: Optional[RoutingConfig] = None,
) -> AgentState:
    """
    Supervisor node: classifies intent and routes to the appropriate agent.

    Uses heuristic keyword matching. Supports retry/fallback by excluding
    previously failed agents from consideration.

    The *routing_config* can be passed directly or placed in
    ``config["configurable"]["routing_config"]``.

    Args:
        state: Current graph state with user message.
        config: LangGraph config dict.
        routing_config: Explicit RoutingConfig override.

    Returns:
        Updated state dict with next_agent, routing_confidence, routing_reason.
    """
    start_time = time.time()

    # Resolve routing config
    rc = routing_config
    if rc is None and config:
        rc = config.get("configurable", {}).get("routing_config")
    if rc is None:
        rc = _EMPTY_CONFIG

    try:
        # Get user's last message
        messages = state["messages"]
        last_user_msg = None
        for msg in reversed(messages):
            if msg.type == "human":
                last_user_msg = msg.content
                break

        if not last_user_msg:
            return {
                "next_agent": "END",
                "routing_confidence": 0.0,
                "routing_reason": "No user message found",
                "error": "No user message to route",
            }

        # Context
        uploaded_files = state.get("uploaded_files", [])
        has_documents = len(uploaded_files) > 0
        failed_agents = state.get("failed_agents", [])
        failed_genie_spaces = state.get("failed_genie_spaces", [])
        retry_count = state.get("retry_count", 0)
        existing_metadata = state.get("metadata", {})

        # Check for suggested retry from response_checker
        suggested_retry = existing_metadata.get("suggested_retry")

        if retry_count > 0 and suggested_retry:
            routing_decision = suggested_retry
            routing_decision["reason"] = (
                f"Retry {retry_count}: {suggested_retry.get('reason', 'fallback')}"
            )
        else:
            routing_decision = heuristic_routing(
                last_user_msg,
                rc,
                has_documents=has_documents,
                failed_agents=failed_agents + failed_genie_spaces,
            )

        execution_time = (time.time() - start_time) * 1000

        # Track thinking step
        thinking_steps = list(state.get("thinking_steps", []))
        retry_prefix = f"Retry {retry_count}: " if retry_count > 0 else ""
        space_suffix = (
            f" ({routing_decision.get('genie_space')} space)"
            if routing_decision.get("genie_space")
            else ""
        )
        thinking_steps.append({
            "type": "routing",
            "agent": routing_decision["agent"],
            "message": (
                f"{retry_prefix}Routing to {routing_decision['agent']}"
                f"{space_suffix} - {routing_decision['reason']}"
            ),
            "timestamp": time.time(),
            "metadata": {
                "confidence": routing_decision["confidence"],
                "failed_agents": failed_agents,
                "failed_genie_spaces": failed_genie_spaces,
                "is_retry": retry_count > 0,
            },
        })

        # Build metadata
        routing_metadata = {**existing_metadata}
        routing_metadata.pop("suggested_retry", None)
        if routing_decision.get("genie_space"):
            routing_metadata["genie_space"] = routing_decision["genie_space"]
        if routing_decision.get("retrieval_spec"):
            routing_metadata["retrieval_spec"] = routing_decision["retrieval_spec"]

        result: Dict[str, Any] = {
            "next_agent": routing_decision["agent"],
            "routing_confidence": routing_decision["confidence"],
            "routing_reason": routing_decision["reason"],
            "execution_time_ms": execution_time,
            "thinking_steps": thinking_steps,
            "metadata": routing_metadata,
        }

        if routing_decision.get("alternative_routes"):
            result["alternative_routes"] = routing_decision["alternative_routes"]

        return result

    except Exception as exc:
        return {
            "next_agent": "END",
            "routing_confidence": 0.0,
            "routing_reason": f"Routing error: {exc}",
            "error": str(exc),
            "execution_time_ms": (time.time() - start_time) * 1000,
        }
