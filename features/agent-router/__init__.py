"""
Agent Router feature — configurable LangGraph multi-agent supervisor.

Provides intent classification, routing, graph construction, and
response validation with retry logic. All agent nodes, keyword lists,
and model names are injected at configuration time.
"""

from .state import AgentState, ExecutionMetadata, create_initial_state, extract_final_response
from .supervisor import RoutingConfig, supervisor_node, heuristic_routing
from .graph import create_graph, route_to_agent, route_after_check
from .router import LLMRouter, RouteDecision

__all__ = [
    # State
    "AgentState",
    "ExecutionMetadata",
    "create_initial_state",
    "extract_final_response",
    # Supervisor
    "RoutingConfig",
    "supervisor_node",
    "heuristic_routing",
    # Graph
    "create_graph",
    "route_to_agent",
    "route_after_check",
    # LLM Router
    "LLMRouter",
    "RouteDecision",
]
