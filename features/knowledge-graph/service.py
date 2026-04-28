"""
Knowledge Graph service — entity and relationship CRUD.

Provides entity extraction, relationship mapping, and context retrieval.
The database connection is injected via a ``connection_factory`` callable
passed at construction time (no singleton, no hardcoded import).

Usage:
    from features.knowledge_graph import KnowledgeGraphService

    async def my_conn_factory():
        import asyncpg
        return await asyncpg.connect("postgresql://...")

    kg = KnowledgeGraphService(connection_factory=my_conn_factory)
    entity = await kg.create_entity(name="revenue", entity_type="concept")
"""

import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Callable, Coroutine, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configurable defaults
# ---------------------------------------------------------------------------

DEFAULT_ENTITY_TYPES = frozenset({
    "table",
    "file",
    "concept",
    "insight",
    "query",
})

DEFAULT_RELATION_TYPES = frozenset({
    "derived_from",
    "related_to",
    "used_by",
    "contains",
})


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class KnowledgeEntity:
    """Represents a node in the knowledge graph."""

    entity_id: str
    entity_type: str
    name: str
    description: Optional[str] = None
    embedding_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    source: Optional[str] = None
    usage_count: int = 0
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> "KnowledgeEntity":
        """Construct from a database row dict."""
        return cls(
            entity_id=str(row["entity_id"]),
            entity_type=row["entity_type"],
            name=row["name"],
            description=row.get("description"),
            embedding_id=row.get("embedding_id"),
            metadata=row.get("metadata") or {},
            source=row.get("source"),
            usage_count=row.get("usage_count", 0),
            created_at=str(row["created_at"]) if row.get("created_at") else None,
            updated_at=str(row["updated_at"]) if row.get("updated_at") else None,
        )


@dataclass
class KnowledgeRelation:
    """Represents an edge in the knowledge graph."""

    relation_id: str
    source_id: str
    target_id: str
    relationship: str
    confidence: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> "KnowledgeRelation":
        """Construct from a database row dict."""
        return cls(
            relation_id=str(row["relation_id"]),
            source_id=str(row["source_id"]),
            target_id=str(row["target_id"]),
            relationship=row["relationship"],
            confidence=row.get("confidence", 1.0),
            metadata=row.get("metadata") or {},
            created_at=str(row["created_at"]) if row.get("created_at") else None,
        )


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class KnowledgeGraphService:
    """
    Async service for managing a knowledge graph in PostgreSQL.

    All database access goes through the ``connection_factory`` callable
    provided at init time. No global singletons.

    Args:
        connection_factory: Async callable that returns an asyncpg connection.
        embedding_factory: Optional async callable that generates an embedding
            ID from (entity_id, name, description). Return None to skip.
    """

    def __init__(
        self,
        connection_factory: Callable[[], Coroutine[Any, Any, Any]],
        embedding_factory: Optional[
            Callable[[str, str, str], Coroutine[Any, Any, Optional[str]]]
        ] = None,
    ):
        self._connection_factory = connection_factory
        self._embedding_factory = embedding_factory
        self._conn: Optional[Any] = None

    async def _get_conn(self) -> Any:
        """Lazily acquire a database connection."""
        if self._conn is None:
            self._conn = await self._connection_factory()
        return self._conn

    async def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            await self._conn.close()
            self._conn = None

    # ================================================================
    # Entity CRUD
    # ================================================================

    async def add_entity(
        self,
        name: str,
        entity_type: str,
        description: Optional[str] = None,
        source: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        generate_embedding: bool = True,
    ) -> KnowledgeEntity:
        """
        Create a new knowledge entity.

        Args:
            name: Entity name.
            entity_type: Type (e.g. 'table', 'concept', 'insight').
            description: Detailed description.
            source: How this entity was created (e.g. 'user_upload', 'chat').
            metadata: Additional JSON metadata.
            generate_embedding: Whether to generate a vector embedding.

        Returns:
            The created KnowledgeEntity.
        """
        conn = await self._get_conn()
        entity_id = str(uuid.uuid4())
        now = datetime.utcnow()

        embedding_id = None
        if generate_embedding and description and self._embedding_factory:
            embedding_id = await self._embedding_factory(entity_id, name, description)

        await conn.execute(
            """
            INSERT INTO knowledge_entities
                (entity_id, entity_type, name, description, embedding_id,
                 metadata, source, usage_count, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, 0, $8, $9)
            """,
            entity_id,
            entity_type,
            name,
            description,
            embedding_id,
            json.dumps(metadata or {}),
            source,
            now,
            now,
        )

        logger.info("[KG] Created entity: %s (%s: %s)", entity_id, entity_type, name)

        return KnowledgeEntity(
            entity_id=entity_id,
            entity_type=entity_type,
            name=name,
            description=description,
            embedding_id=embedding_id,
            metadata=metadata or {},
            source=source,
            usage_count=0,
            created_at=now.isoformat(),
            updated_at=now.isoformat(),
        )

    async def get_entity(self, entity_id: str) -> Optional[KnowledgeEntity]:
        """Get an entity by ID. Returns None if not found."""
        conn = await self._get_conn()
        row = await conn.fetchrow(
            "SELECT * FROM knowledge_entities WHERE entity_id = $1",
            entity_id,
        )
        return KnowledgeEntity.from_row(dict(row)) if row else None

    async def search_entities(
        self,
        query: str,
        entity_types: Optional[List[str]] = None,
        limit: int = 10,
    ) -> List[Tuple[KnowledgeEntity, float]]:
        """
        Search entities by text match (ILIKE on name and description).

        Args:
            query: Search text.
            entity_types: Optional filter by entity types.
            limit: Maximum results.

        Returns:
            List of (entity, score) tuples sorted by usage_count desc.
        """
        conn = await self._get_conn()

        conditions = ["(name ILIKE $1 OR description ILIKE $1)"]
        params: list[Any] = [f"%{query}%"]
        idx = 2

        if entity_types:
            placeholders = ", ".join(f"${idx + i}" for i in range(len(entity_types)))
            conditions.append(f"entity_type IN ({placeholders})")
            params.extend(entity_types)
            idx += len(entity_types)

        sql = f"""
            SELECT *, 1.0 AS score
            FROM knowledge_entities
            WHERE {' AND '.join(conditions)}
            ORDER BY usage_count DESC
            LIMIT ${idx}
        """
        params.append(limit)

        rows = await conn.fetch(sql, *params)
        return [(KnowledgeEntity.from_row(dict(r)), r["score"]) for r in rows]

    async def increment_usage(self, entity_id: str) -> bool:
        """Increment the usage_count for an entity. Returns True on success."""
        conn = await self._get_conn()
        result = await conn.execute(
            """
            UPDATE knowledge_entities
            SET usage_count = usage_count + 1, updated_at = $1
            WHERE entity_id = $2
            """,
            datetime.utcnow(),
            entity_id,
        )
        return "UPDATE 1" in result

    async def delete_entity(self, entity_id: str) -> bool:
        """Delete an entity. Returns True on success."""
        conn = await self._get_conn()
        result = await conn.execute(
            "DELETE FROM knowledge_entities WHERE entity_id = $1",
            entity_id,
        )
        return "DELETE 1" in result

    # ================================================================
    # Relationship CRUD
    # ================================================================

    async def add_relationship(
        self,
        source_id: str,
        target_id: str,
        relationship: str,
        confidence: float = 1.0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> KnowledgeRelation:
        """
        Create a relationship between two entities.

        Uses ON CONFLICT to upsert if the (source, target, relationship)
        triple already exists.

        Args:
            source_id: Source entity ID.
            target_id: Target entity ID.
            relationship: Relationship type (e.g. 'derived_from').
            confidence: Confidence score (0-1).
            metadata: Additional JSON metadata.

        Returns:
            The created KnowledgeRelation.
        """
        conn = await self._get_conn()
        relation_id = str(uuid.uuid4())
        now = datetime.utcnow()

        await conn.execute(
            """
            INSERT INTO knowledge_relations
                (relation_id, source_id, target_id, relationship,
                 confidence, metadata, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT (source_id, target_id, relationship) DO UPDATE
            SET confidence = $5, metadata = $6
            """,
            relation_id,
            source_id,
            target_id,
            relationship,
            confidence,
            json.dumps(metadata or {}),
            now,
        )

        logger.info(
            "[KG] Created relation: %s -%s-> %s",
            source_id, relationship, target_id,
        )

        return KnowledgeRelation(
            relation_id=relation_id,
            source_id=source_id,
            target_id=target_id,
            relationship=relationship,
            confidence=confidence,
            metadata=metadata or {},
            created_at=now.isoformat(),
        )

    async def get_relationships(
        self,
        entity_id: str,
        relation_types: Optional[List[str]] = None,
        direction: str = "both",
    ) -> List[Tuple[KnowledgeEntity, KnowledgeRelation]]:
        """
        Get entities related to a given entity.

        Args:
            entity_id: The entity to query from.
            relation_types: Optional filter by relationship types.
            direction: 'outgoing', 'incoming', or 'both'.

        Returns:
            List of (related_entity, relation) tuples.
        """
        conn = await self._get_conn()
        results: List[Tuple[KnowledgeEntity, KnowledgeRelation]] = []

        # -- Outgoing --
        if direction in ("both", "outgoing"):
            if relation_types:
                rows = await conn.fetch(
                    """
                    SELECT e.*, r.relation_id, r.source_id, r.target_id,
                           r.relationship, r.confidence,
                           r.metadata AS rel_metadata, r.created_at AS rel_created
                    FROM knowledge_relations r
                    JOIN knowledge_entities e ON e.entity_id = r.target_id
                    WHERE r.source_id = $1 AND r.relationship = ANY($2)
                    """,
                    entity_id,
                    relation_types,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT e.*, r.relation_id, r.source_id, r.target_id,
                           r.relationship, r.confidence,
                           r.metadata AS rel_metadata, r.created_at AS rel_created
                    FROM knowledge_relations r
                    JOIN knowledge_entities e ON e.entity_id = r.target_id
                    WHERE r.source_id = $1
                    """,
                    entity_id,
                )

            for row in rows:
                entity = KnowledgeEntity.from_row(dict(row))
                relation = KnowledgeRelation(
                    relation_id=str(row["relation_id"]),
                    source_id=str(row["source_id"]),
                    target_id=str(row["target_id"]),
                    relationship=row["relationship"],
                    confidence=row["confidence"],
                    metadata=row.get("rel_metadata") or {},
                    created_at=(
                        str(row["rel_created"]) if row.get("rel_created") else None
                    ),
                )
                results.append((entity, relation))

        # -- Incoming --
        if direction in ("both", "incoming"):
            if relation_types:
                rows = await conn.fetch(
                    """
                    SELECT e.*, r.relation_id, r.source_id, r.target_id,
                           r.relationship, r.confidence,
                           r.metadata AS rel_metadata, r.created_at AS rel_created
                    FROM knowledge_relations r
                    JOIN knowledge_entities e ON e.entity_id = r.source_id
                    WHERE r.target_id = $1 AND r.relationship = ANY($2)
                    """,
                    entity_id,
                    relation_types,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT e.*, r.relation_id, r.source_id, r.target_id,
                           r.relationship, r.confidence,
                           r.metadata AS rel_metadata, r.created_at AS rel_created
                    FROM knowledge_relations r
                    JOIN knowledge_entities e ON e.entity_id = r.source_id
                    WHERE r.target_id = $1
                    """,
                    entity_id,
                )

            for row in rows:
                entity = KnowledgeEntity.from_row(dict(row))
                relation = KnowledgeRelation(
                    relation_id=str(row["relation_id"]),
                    source_id=str(row["source_id"]),
                    target_id=str(row["target_id"]),
                    relationship=row["relationship"],
                    confidence=row["confidence"],
                    metadata=row.get("rel_metadata") or {},
                    created_at=(
                        str(row["rel_created"]) if row.get("rel_created") else None
                    ),
                )
                results.append((entity, relation))

        return results

    # ================================================================
    # Context retrieval
    # ================================================================

    async def get_context_for_query(
        self,
        query: str,
        max_entities: int = 5,
    ) -> List[KnowledgeEntity]:
        """
        Retrieve relevant context entities for a query.

        Searches by text, increments usage counts, and returns entities
        suitable for prompt injection.

        Args:
            query: User query.
            max_entities: Maximum entities to return.

        Returns:
            List of relevant KnowledgeEntity objects.
        """
        results = await self.search_entities(query=query, limit=max_entities)
        entities = [entity for entity, _score in results]

        for entity in entities:
            await self.increment_usage(entity.entity_id)

        return entities
