"""
Lakebase (PostgreSQL) database connectivity for FastAPI app.

Provides connection management with OAuth token injection for Databricks Apps.
"""

from foundation.config import get_settings
from sqlalchemy import create_engine, text, event
from .credentials import LakebaseCredentialProvider

import logging

logger = logging.getLogger(__name__)

_credential_provider = LakebaseCredentialProvider()


def create_sync_engine():
    """
    Create a SQLAlchemy engine for PostgreSQL on Lakebase with OAuth token.
    """
    settings = get_settings()
    if not settings.pg_connection_string:
        raise ValueError("Lakebase not configured - PGHOST not set")

    postgres_pool = create_engine(settings.pg_connection_string)

    @event.listens_for(postgres_pool, "do_connect")
    def provide_token(dialect, conn_rec, cargs, cparams):
        credential = _credential_provider.get_credential()
        cparams["password"] = credential.token

    return postgres_pool


def test_database_connection():
    engine = create_sync_engine()
    try:
        with engine.connect() as connection:
            result = connection.execute(text("SELECT version();"))
            version = result.scalar()
        logger.info(f"Connection successful - PostgreSQL Version: {version}")
    except Exception as e:
        logger.info(f"Connection failed: {e}")


def get_connection_string() -> str:
    """
    Get Lakebase PostgreSQL connection string for LangGraph checkpointing.

    Returns:
        Connection string suitable for PostgresSaver.from_conn_string()
    """
    settings = get_settings()
    return settings.pg_connection_string


async def get_async_connection():
    """
    Get async PostgreSQL connection for data access layer.

    Uses asyncpg for lightweight async operations (feedback, preferences).
    Note: Connection password is injected via OAuth token from credential provider.
    """
    import asyncpg

    settings = get_settings()
    # Get base connection string
    conn_string = settings.pg_connection_string

    # Get OAuth token for password
    credential = _credential_provider.get_credential()

    # Parse connection string and inject token as password
    # asyncpg expects: postgresql://user:password@host:port/database
    # Replace placeholder password with actual OAuth token
    if "postgresql://" in conn_string:
        parts = conn_string.replace("postgresql://", "").split("@")
        if len(parts) == 2:
            user_part = parts[0]
            host_part = parts[1]

            # Extract user (before colon if present)
            user = user_part.split(":")[0] if ":" in user_part else user_part

            # Build new connection string with OAuth token
            conn_string = f"postgresql://{user}:{credential.token}@{host_part}"

    # Create async connection
    conn = await asyncpg.connect(conn_string)
    return conn


if __name__ == "__main__":
    # Test the regular data layer
    test_database_connection()
