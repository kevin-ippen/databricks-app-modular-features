"""
Workflow Checkpoint feature module.

Provides LangGraph state persistence via Lakebase (PostgreSQL) using
PostgresSaver. Handles OAuth token injection and schema auto-setup.

Requirements:
    pip install langgraph-checkpoint-postgres
"""

from .checkpointer import (
    create_lakebase_checkpointer,
    get_checkpoint_connection_string,
)

__all__ = [
    "create_lakebase_checkpointer",
    "get_checkpoint_connection_string",
]
