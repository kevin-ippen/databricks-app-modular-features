"""Schema auto-initialization for Lakebase tables."""
import logging
logger = logging.getLogger(__name__)

async def initialize_schema(connection_factory, ddl_path: str) -> None:
    """Execute DDL from a SQL file to create tables if they don't exist."""
    with open(ddl_path) as f:
        ddl = f.read()
    conn = await connection_factory()
    try:
        for statement in ddl.split(';'):
            stmt = statement.strip()
            if stmt:
                await conn.execute(stmt)
        logger.info(f"Schema initialized from {ddl_path}")
    finally:
        await conn.close()
