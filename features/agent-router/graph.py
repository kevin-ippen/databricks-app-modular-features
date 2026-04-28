"""
LangGraph graph construction for the multi-agent router.

Builds a StateGraph that routes user queries through a supervisor node
to specialised agent nodes, with response checking and retry logic.

All agent nodes are passed in at construction time -- nothing is
hardcoded or imported from a specific application.

Usage:
    from features.agent_router.graph import create_graph
    from features.agent_router.supervisor import supervisor_node

    agents = {
        "genie_agent": my_genie_node,
        "rag_agent": my_rag_node,
        "websearch_agent": my_websearch_node,
        "general_agent": my_general_node,
    }

    routing_map = {
        "genie": "genie_agent",
        "sql": "genie_agent",
        "rag": "rag_agent",
        "websearch": "websearch_agent",
        "general": "general_agent",
        "END": "__end__",
    }

    graph = create_graph(
        agents=agents,
        routing_map=routing_map,
        supervisor_fn=supervisor_node,
    )
"""

from typing import Any, Callable, Dict, Optional

from langgraph.graph import StateGraph, END

from .state import AgentState


# ---------------------------------------------------------------------------
# Conditional routing functions
# ---------------------------------------------------------------------------

def route_to_agent(
    state: AgentState,
    routing_map: Optional[Dict[str, str]] = None,
) -> str:
    """
    Conditional routing function: reads ``next_agent`` from state and
    maps it to a graph node name via *routing_map*.

    If *routing_map* is None, the raw ``next_agent`` value is returned
    (suitable when node names match agent names exactly).

    Args:
        state: Current graph state with routing decision.
        routing_map: Optional mapping from intent names to node names.

    Returns:
        Node name to execute next, or ``END``.
    """
    next_agent = state.get("next_agent", "END")

    if next_agent == "END":
        return END

    if routing_map:
        return routing_map.get(next_agent, END)

    return next_agent


def route_after_check(state: AgentState) -> str:
    """
    Route after response validation.

    If ``agent_failed`` is True and retries remain, loops back to
    the supervisor for re-routing. Otherwise ends execution.

    Args:
        state: Current graph state with failure-detection results.

    Returns:
        ``"supervisor"`` to retry, or ``END`` to finish.
    """
    if state.get("agent_failed", False):
        return "supervisor"
    return END


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

def create_graph(
    agents: Dict[str, Callable],
    routing_map: Dict[str, str],
    supervisor_fn: Callable,
    *,
    response_checker_fn: Optional[Callable] = None,
    checkpointer: Optional[Any] = None,
    enable_debug: bool = False,
) -> Any:
    """
    Build and compile a LangGraph multi-agent supervisor graph.

    Graph structure::

        START -> supervisor -> [agent_1 | agent_2 | ... | END]
                                   |
                            response_checker (optional)
                                   |
                          supervisor (retry) or END

    Args:
        agents: Mapping of node_name -> async callable.
            Each callable must accept ``(state: AgentState, config: dict)``
            and return an AgentState update dict.
        routing_map: Mapping from intent names (produced by supervisor) to
            node names in *agents*. Must include ``"END"`` mapped to
            ``"__end__"`` or the sentinel ``langgraph.graph.END``.
        supervisor_fn: The supervisor node callable.
        response_checker_fn: Optional response validation node. When
            provided, all agent outputs pass through it before ending.
            The checker can set ``agent_failed=True`` to trigger a retry.
        checkpointer: Optional LangGraph checkpointer for state persistence.
        enable_debug: Enable LangGraph debug mode.

    Returns:
        A compiled LangGraph ``StateGraph`` ready for invocation.
    """
    graph = StateGraph(AgentState)

    # -- Supervisor --
    graph.add_node("supervisor", supervisor_fn)

    # -- Agent nodes --
    for node_name, node_fn in agents.items():
        graph.add_node(node_name, node_fn)

    # -- Response checker (optional) --
    has_checker = response_checker_fn is not None
    if has_checker:
        graph.add_node("response_checker", response_checker_fn)

    # -- Entry edge --
    graph.add_edge("__start__", "supervisor")

    # -- Build the conditional edge map for supervisor -> agents --
    # Normalise END sentinel
    edge_map: Dict[str, str] = {}
    for intent_name, node_name in routing_map.items():
        if intent_name == "END" or node_name in ("__end__", END):
            edge_map[END] = END
        else:
            edge_map[node_name] = node_name

    # The routing function needs access to routing_map, so we close over it
    def _route(state: AgentState) -> str:
        return route_to_agent(state, routing_map)

    graph.add_conditional_edges("supervisor", _route, edge_map)

    # -- Agent -> checker -> END (or retry) --
    if has_checker:
        for node_name in agents:
            graph.add_edge(node_name, "response_checker")

        graph.add_conditional_edges(
            "response_checker",
            route_after_check,
            {
                "supervisor": "supervisor",
                END: END,
            },
        )
    else:
        # No checker -- agents go straight to END
        for node_name in agents:
            graph.add_edge(node_name, END)

    # -- Compile --
    compiled = graph.compile(
        checkpointer=checkpointer,
        debug=enable_debug,
    )
    return compiled
