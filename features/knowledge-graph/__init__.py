"""
Knowledge Graph feature — entity and relationship management.

Provides async CRUD for knowledge entities and relationships,
backed by any asyncpg-compatible PostgreSQL connection (e.g. Lakebase).
"""

from .service import (
    KnowledgeGraphService,
    KnowledgeEntity,
    KnowledgeRelation,
    DEFAULT_ENTITY_TYPES,
    DEFAULT_RELATION_TYPES,
)

__all__ = [
    "KnowledgeGraphService",
    "KnowledgeEntity",
    "KnowledgeRelation",
    "DEFAULT_ENTITY_TYPES",
    "DEFAULT_RELATION_TYPES",
]
