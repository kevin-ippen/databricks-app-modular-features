"""
LangGraph state schema for a multi-agent router.

Defines the shared state that flows through all nodes in the graph,
plus helpers to create initial state and extract the final response.
"""

from typing import TypedDict, Annotated, List, Dict, Any, Optional
from langchain_core.messages import BaseMessage, HumanMessage
from langgraph.graph.message import add_messages


# ---------------------------------------------------------------------------
# Execution metadata (for transparency / observability)
# ---------------------------------------------------------------------------

class ExecutionMetadata(TypedDict, total=False):
    """
    Detailed execution metadata populated by agent nodes.

    Displayed in a collapsible "Execution Details" section in the UI.
    """

    agent_used: str
    """Which agent handled the request."""

    tools_called: List[str]
    """Tool/function names invoked during execution."""

    sql_queries: List[str]
    """SQL queries generated and executed."""

    tables_accessed: List[str]
    """Tables that were queried."""

    documents_retrieved: List[str]
    """Document IDs/names from vector search."""

    search_engine: str
    """Search engine used (e.g. 'you.com')."""

    search_results_count: int
    """Number of search results retrieved."""

    execution_time_ms: float
    """Time spent in this agent (milliseconds)."""

    row_count: int
    """Number of rows returned from a SQL query."""

    query_success: bool
    """Whether the operation succeeded."""

    error_message: Optional[str]
    """Error details if query_success is False."""

    retry_attempt: int
    """Which retry attempt this was (0 = first try)."""


# ---------------------------------------------------------------------------
# Core agent state
# ---------------------------------------------------------------------------

class AgentState(TypedDict):
    """
    Shared state that flows through every node in the LangGraph agent.

    The ``messages`` field uses the ``add_messages`` reducer so new messages
    are appended rather than replacing the list.
    """

    # -- Core conversation --------------------------------------------------
    messages: Annotated[List[BaseMessage], add_messages]
    """Conversation history (HumanMessage, AIMessage, SystemMessage, ...)."""

    # -- Routing & agent selection ------------------------------------------
    next_agent: str
    """Target agent for the current turn (e.g. "sql", "rag", "END")."""

    routing_confidence: float
    """Confidence score (0-1) for the routing decision."""

    routing_reason: str
    """Human-readable explanation of the routing choice."""

    # -- Session & user context ---------------------------------------------
    session_id: str
    """Unique session identifier (used as thread_id for checkpointing)."""

    user_id: Optional[str]
    """Authenticated user identifier."""

    # -- Uploaded files / documents -----------------------------------------
    uploaded_files: List[Dict[str, Any]]
    """Files uploaded by the user (file_id, filename, path, processed, ...)."""

    # -- Execution metadata -------------------------------------------------
    tools_used: List[str]
    """Tool names called during agent execution."""

    execution_time_ms: float
    """Total execution time for the current agent (ms)."""

    sources: List[Dict[str, Any]]
    """Source citations from RAG or web search."""

    # -- Error handling & retry ---------------------------------------------
    error: Optional[str]
    """Error message if agent execution failed."""

    retry_count: int
    """Number of retry attempts for the current query."""

    max_retries: int
    """Maximum retry attempts allowed (default 2-3)."""

    failed_agents: List[str]
    """Agents that already failed for this query."""

    failed_genie_spaces: List[str]
    """Genie spaces that failed (for space-level fallback)."""

    alternative_routes: List[Dict[str, Any]]
    """Alternative routing options ranked by confidence."""

    agent_failed: bool
    """Flag set by response_checker when the agent could not answer."""

    failure_reason: Optional[str]
    """Pattern that triggered failure detection."""

    # -- Thinking / streaming transparency ----------------------------------
    thinking_steps: List[Dict[str, Any]]
    """Agent thinking trace (type, agent, message, timestamp, metadata)."""

    # -- Advanced / extensible ----------------------------------------------
    human_feedback: Optional[Dict[str, Any]]
    """User feedback for human-in-the-loop patterns."""

    metadata: Dict[str, Any]
    """Flexible field for agent-specific data."""

    execution_metadata: Optional[ExecutionMetadata]
    """Detailed execution information for transparency."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def create_initial_state(
    user_message: str,
    session_id: str,
    user_id: Optional[str] = None,
    uploaded_files: Optional[List[Dict[str, Any]]] = None,
    max_retries: int = 3,
) -> AgentState:
    """
    Create the initial state dict for a new user query.

    Args:
        user_message: The user's input text.
        session_id: Session identifier for checkpointing.
        user_id: Optional authenticated user identifier.
        uploaded_files: Optional list of uploaded file descriptors.
        max_retries: Maximum retry attempts (default 3).

    Returns:
        A fully-initialised AgentState.
    """
    return AgentState(
        messages=[HumanMessage(content=user_message)],
        next_agent="supervisor",
        routing_confidence=0.0,
        routing_reason="",
        session_id=session_id,
        user_id=user_id,
        uploaded_files=uploaded_files or [],
        tools_used=[],
        execution_time_ms=0.0,
        sources=[],
        error=None,
        retry_count=0,
        max_retries=max_retries,
        failed_agents=[],
        failed_genie_spaces=[],
        alternative_routes=[],
        agent_failed=False,
        failure_reason=None,
        thinking_steps=[],
        human_feedback=None,
        metadata={},
        execution_metadata=None,
    )


def extract_final_response(state: AgentState) -> Dict[str, Any]:
    """
    Extract the final response from graph state for API return.

    Converts the LangGraph state into a flat dict suitable for
    serialisation as a JSON API response.

    Args:
        state: Final graph state after execution.

    Returns:
        Dict with response content, metadata, and error info.
    """
    ai_messages = [msg for msg in state["messages"] if msg.type == "ai"]
    if not ai_messages:
        return {
            "content": "No response generated",
            "error": state.get("error", "Unknown error"),
        }

    last_message = ai_messages[-1]

    return {
        "content": last_message.content,
        "agent_used": state.get("next_agent", "unknown"),
        "routing_confidence": state.get("routing_confidence", 0.0),
        "routing_reason": state.get("routing_reason", ""),
        "tools_used": state.get("tools_used", []),
        "execution_time_ms": state.get("execution_time_ms", 0.0),
        "sources": state.get("sources", []),
        "error": state.get("error"),
        "execution_metadata": state.get("execution_metadata"),
    }
