"""
LangGraph workflow checkpointing via Lakebase (PostgreSQL).

Creates a PostgresSaver checkpointer for LangGraph state persistence,
with support for Databricks OAuth token injection.

Requirements:
    pip install langgraph-checkpoint-postgres

Usage::

    from features.workflow_checkpoint import create_lakebase_checkpointer

    checkpointer = create_lakebase_checkpointer(
        connection_string="postgresql://user@host:port/database",
        schema="my_app",
    )
    # checkpointer.setup()  -- auto-creates tables if needed

    graph = create_graph(checkpointer=checkpointer)
"""

import logging
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from langgraph.checkpoint.postgres import PostgresSaver
else:
    try:
        from langgraph.checkpoint.postgres import PostgresSaver
    except ImportError:
        PostgresSaver = None  # type: ignore

logger = logging.getLogger(__name__)


def get_checkpoint_connection_string(
    host: str,
    token: str,
    database: str,
    port: int = 5432,
    user: str = "token",
    sslmode: str = "require",
) -> str:
    """
    Build a PostgreSQL DSN string for Lakebase with an OAuth token as password.

    This is the format expected by PostgresSaver.from_conn_string().

    Args:
        host: Lakebase host (e.g., "my-workspace.cloud.databricks.com").
        token: OAuth or PAT token used as the password.
        database: Database name on Lakebase.
        port: PostgreSQL port (default 5432).
        user: Username (default "token" for Databricks OAuth).
        sslmode: SSL mode (default "require").

    Returns:
        Connection string like ``postgresql://token:XXXXX@host:5432/db?sslmode=require``
    """
    # URL-encode the token in case it contains special characters
    from urllib.parse import quote_plus
    encoded_token = quote_plus(token)
    return f"postgresql://{user}:{encoded_token}@{host}:{port}/{database}?sslmode={sslmode}"


def create_lakebase_checkpointer(
    connection_string: str,
    schema: str = "public",
    auto_setup: bool = True,
) -> Optional["PostgresSaver"]:
    """
    Create a PostgresSaver checkpointer using a Lakebase connection.

    Enables conversation persistence and resumability across sessions
    in LangGraph workflows.

    Args:
        connection_string: Full PostgreSQL connection string (DSN).
                           Use get_checkpoint_connection_string() to build one
                           with OAuth token injection.
        schema: PostgreSQL schema for checkpoint tables.
                Default "public". Use a custom schema (e.g., "my_app")
                to isolate checkpoint tables from other app data.
        auto_setup: If True, call checkpointer.setup() to auto-create
                    the required tables on first use.

    Returns:
        PostgresSaver instance connected to Lakebase, or None if the
        ``langgraph-checkpoint-postgres`` package is not installed.

    Raises:
        RuntimeError: If Lakebase connection is configured but cannot
                      be established.

    Example::

        from databricks.sdk import WorkspaceClient

        w = WorkspaceClient()
        token = w.config.token

        conn_string = get_checkpoint_connection_string(
            host="my-lakebase-host.com",
            token=token,
            database="my_database",
        )
        checkpointer = create_lakebase_checkpointer(conn_string, schema="my_app")

        # Use with LangGraph
        graph = workflow.compile(checkpointer=checkpointer)
    """
    if PostgresSaver is None:
        logger.warning(
            "PostgresSaver not available -- install langgraph-checkpoint-postgres "
            "to enable workflow checkpointing"
        )
        return None

    try:
        checkpointer = PostgresSaver.from_conn_string(
            connection_string,
            schema=schema,
        )

        if auto_setup:
            checkpointer.setup()

        return checkpointer

    except Exception as e:
        raise RuntimeError(f"Failed to create Lakebase checkpointer: {e}") from e
