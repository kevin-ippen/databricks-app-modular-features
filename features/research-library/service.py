"""
Research Library service — PostgreSQL (Lakebase) for application state.

Handles: collections, annotations, search history, user preferences.
Connection parameters are injected via constructor (no hardcoded references).
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Any, Optional

import psycopg2
import psycopg2.extras

logger = logging.getLogger(__name__)


class ResearchLibraryService:
    """
    Research Library backed by PostgreSQL (Lakebase).

    Args:
        connection_params: Dict with keys: host, port, database, user, password.
                           Falls back to environment variables:
                           LAKEBASE_HOST, LAKEBASE_PORT, LAKEBASE_DATABASE,
                           LAKEBASE_USER, LAKEBASE_PASSWORD.
        sslmode: SSL mode for PostgreSQL connection. Default "require".
    """

    def __init__(
        self,
        connection_params: Optional[dict[str, Any]] = None,
        sslmode: str = "require",
    ):
        params = connection_params or {}
        self._host = params.get("host") or os.environ.get("LAKEBASE_HOST", "localhost")
        self._port = int(params.get("port") or os.environ.get("LAKEBASE_PORT", "5432"))
        self._database = params.get("database") or os.environ.get("LAKEBASE_DATABASE", "research")
        self._user = params.get("user") or os.environ.get("LAKEBASE_USER", "")
        self._password = params.get("password") or os.environ.get("LAKEBASE_PASSWORD", "")
        self._sslmode = sslmode

    @contextmanager
    def _get_connection(self):
        """Yield a PostgreSQL connection."""
        conn = psycopg2.connect(
            host=self._host,
            port=self._port,
            database=self._database,
            user=self._user,
            password=self._password,
            sslmode=self._sslmode,
        )
        try:
            yield conn
        finally:
            conn.close()

    def initialize_schema(self):
        """Create tables if they don't exist. Call at app startup."""
        schema_sql = """
        CREATE TABLE IF NOT EXISTS collections (
            id              SERIAL PRIMARY KEY,
            name            VARCHAR(255) NOT NULL,
            description     TEXT,
            created_by      VARCHAR(255) NOT NULL,
            created_at      TIMESTAMPTZ DEFAULT NOW(),
            updated_at      TIMESTAMPTZ DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS collection_docs (
            collection_id   INTEGER REFERENCES collections(id) ON DELETE CASCADE,
            doc_id          VARCHAR(255) NOT NULL,
            added_at        TIMESTAMPTZ DEFAULT NOW(),
            PRIMARY KEY (collection_id, doc_id)
        );

        CREATE TABLE IF NOT EXISTS annotations (
            id              SERIAL PRIMARY KEY,
            doc_id          VARCHAR(255) NOT NULL,
            chunk_id        VARCHAR(255),
            user_id         VARCHAR(255) NOT NULL,
            note            TEXT NOT NULL,
            created_at      TIMESTAMPTZ DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS search_history (
            id              SERIAL PRIMARY KEY,
            user_id         VARCHAR(255) NOT NULL,
            query           TEXT NOT NULL,
            mode            VARCHAR(50),
            result_count    INTEGER DEFAULT 0,
            created_at      TIMESTAMPTZ DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS user_preferences (
            user_id         VARCHAR(255) PRIMARY KEY,
            persona         VARCHAR(50) DEFAULT 'researcher',
            theme           VARCHAR(20) DEFAULT 'dark',
            default_sources TEXT[],
            updated_at      TIMESTAMPTZ DEFAULT NOW()
        );

        CREATE INDEX IF NOT EXISTS idx_annotations_doc ON annotations(doc_id);
        CREATE INDEX IF NOT EXISTS idx_search_history_user ON search_history(user_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_collections_user ON collections(created_by);
        """
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(schema_sql)
            conn.commit()
        logger.info("Research Library schema initialized")

    # ── Collections ───────────────────────────────────────────────────────────

    def create_collection(self, name: str, description: str, created_by: str) -> dict:
        """Create a new collection. Returns the created row as dict."""
        with self._get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "INSERT INTO collections (name, description, created_by) VALUES (%s, %s, %s) RETURNING *",
                    (name, description, created_by),
                )
                result = dict(cur.fetchone())
            conn.commit()
        return result

    def list_collections(self, user_id: Optional[str] = None) -> list[dict]:
        """List collections, optionally filtered by creator."""
        query = "SELECT * FROM collections"
        params: list = []
        if user_id:
            query += " WHERE created_by = %s"
            params.append(user_id)
        query += " ORDER BY updated_at DESC"

        with self._get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(query, params)
                return [dict(r) for r in cur.fetchall()]

    def get_collection(self, collection_id: int) -> Optional[dict]:
        """Get a single collection by ID."""
        with self._get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM collections WHERE id = %s", (collection_id,))
                row = cur.fetchone()
                return dict(row) if row else None

    def add_doc_to_collection(self, collection_id: int, doc_id: str) -> None:
        """Add a document to a collection (idempotent)."""
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO collection_docs (collection_id, doc_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                    (collection_id, doc_id),
                )
            conn.commit()

    def get_collection_docs(self, collection_id: int) -> list[str]:
        """Get all doc IDs in a collection."""
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT doc_id FROM collection_docs WHERE collection_id = %s", (collection_id,))
                return [row[0] for row in cur.fetchall()]

    def remove_doc_from_collection(self, collection_id: int, doc_id: str) -> None:
        """Remove a document from a collection."""
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM collection_docs WHERE collection_id = %s AND doc_id = %s",
                    (collection_id, doc_id),
                )
            conn.commit()

    # ── Annotations ───────────────────────────────────────────────────────────

    def create_annotation(
        self, doc_id: str, user_id: str, note: str, chunk_id: Optional[str] = None
    ) -> dict:
        """Create an annotation on a document."""
        with self._get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "INSERT INTO annotations (doc_id, chunk_id, user_id, note) VALUES (%s, %s, %s, %s) RETURNING *",
                    (doc_id, chunk_id, user_id, note),
                )
                result = dict(cur.fetchone())
            conn.commit()
        return result

    def list_annotations(self, doc_id: str) -> list[dict]:
        """List all annotations for a document."""
        with self._get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM annotations WHERE doc_id = %s ORDER BY created_at DESC",
                    (doc_id,),
                )
                return [dict(r) for r in cur.fetchall()]

    # ── Search History ────────────────────────────────────────────────────────

    def log_search(self, user_id: str, query: str, mode: str, result_count: int) -> None:
        """Log a search query."""
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO search_history (user_id, query, mode, result_count) VALUES (%s, %s, %s, %s)",
                    (user_id, query, mode, result_count),
                )
            conn.commit()

    def get_recent_searches(self, user_id: str, limit: int = 20) -> list[dict]:
        """Get recent searches for a user."""
        with self._get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM search_history WHERE user_id = %s ORDER BY created_at DESC LIMIT %s",
                    (user_id, limit),
                )
                return [dict(r) for r in cur.fetchall()]

    # ── User Preferences ─────────────────────────────────────────────────────

    def get_preferences(self, user_id: str) -> Optional[dict]:
        """Get user preferences."""
        with self._get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM user_preferences WHERE user_id = %s", (user_id,))
                row = cur.fetchone()
                return dict(row) if row else None

    def upsert_preferences(
        self,
        user_id: str,
        persona: Optional[str] = None,
        theme: Optional[str] = None,
        default_sources: Optional[list[str]] = None,
    ) -> dict:
        """Create or update user preferences."""
        with self._get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO user_preferences (user_id, persona, theme, default_sources)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (user_id) DO UPDATE SET
                        persona = COALESCE(EXCLUDED.persona, user_preferences.persona),
                        theme = COALESCE(EXCLUDED.theme, user_preferences.theme),
                        default_sources = COALESCE(EXCLUDED.default_sources, user_preferences.default_sources),
                        updated_at = NOW()
                    RETURNING *
                    """,
                    (user_id, persona, theme, default_sources),
                )
                result = dict(cur.fetchone())
            conn.commit()
        return result
