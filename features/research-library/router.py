"""
FastAPI routes for Research Library.

Endpoints:
  POST /collections         — create a collection
  GET  /collections         — list collections (optional ?user_id=)
  GET  /collections/{id}    — get collection with docs
  POST /collections/{id}/docs — add doc to collection
  POST /annotations         — create annotation
  GET  /annotations/{doc_id} — list annotations for doc
  GET  /search-history      — get recent searches
  GET  /preferences/{user_id} — get preferences
  POST /preferences/{user_id} — upsert preferences
"""

import asyncio
import logging
from typing import Optional, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .service import ResearchLibraryService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/research-library", tags=["research-library"])


# ── Dependency: service instance ──────────────────────────────────────────────
# In production, override this with a configured instance via app.dependency_overrides

_service: Optional[ResearchLibraryService] = None


def get_service() -> ResearchLibraryService:
    """Get the research library service. Must be initialized at startup."""
    if _service is None:
        raise HTTPException(status_code=503, detail="Research Library service not initialized")
    return _service


def init_service(service: ResearchLibraryService):
    """Initialize the module-level service (call at app startup)."""
    global _service
    _service = service


# ── Request / Response models ─────────────────────────────────────────────────

class CreateCollectionRequest(BaseModel):
    name: str
    description: str = ""
    created_by: str


class AddDocRequest(BaseModel):
    doc_id: str


class CreateAnnotationRequest(BaseModel):
    doc_id: str
    user_id: str
    note: str
    chunk_id: Optional[str] = None


class UpsertPreferencesRequest(BaseModel):
    persona: Optional[str] = None
    theme: Optional[str] = None
    default_sources: Optional[List[str]] = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/collections")
async def create_collection(req: CreateCollectionRequest):
    """Create a new research collection."""
    svc = get_service()
    result = await asyncio.to_thread(
        svc.create_collection, req.name, req.description, req.created_by
    )
    return result


@router.get("/collections")
async def list_collections(user_id: Optional[str] = None):
    """List all collections, optionally filtered by user."""
    svc = get_service()
    results = await asyncio.to_thread(svc.list_collections, user_id)
    return results


@router.get("/collections/{collection_id}")
async def get_collection(collection_id: int):
    """Get a collection with its document IDs."""
    svc = get_service()
    collection = await asyncio.to_thread(svc.get_collection, collection_id)
    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")
    docs = await asyncio.to_thread(svc.get_collection_docs, collection_id)
    return {**collection, "docs": docs}


@router.post("/collections/{collection_id}/docs")
async def add_doc_to_collection(collection_id: int, req: AddDocRequest):
    """Add a document to a collection."""
    svc = get_service()
    await asyncio.to_thread(svc.add_doc_to_collection, collection_id, req.doc_id)
    return {"status": "added", "collection_id": collection_id, "doc_id": req.doc_id}


@router.post("/annotations")
async def create_annotation(req: CreateAnnotationRequest):
    """Create an annotation on a document."""
    svc = get_service()
    result = await asyncio.to_thread(
        svc.create_annotation, req.doc_id, req.user_id, req.note, req.chunk_id
    )
    return result


@router.get("/annotations/{doc_id}")
async def list_annotations(doc_id: str):
    """List all annotations for a document."""
    svc = get_service()
    results = await asyncio.to_thread(svc.list_annotations, doc_id)
    return results


@router.get("/search-history")
async def get_search_history(user_id: str, limit: int = 20):
    """Get recent searches for a user."""
    svc = get_service()
    results = await asyncio.to_thread(svc.get_recent_searches, user_id, limit)
    return results


@router.get("/preferences/{user_id}")
async def get_preferences(user_id: str):
    """Get user preferences."""
    svc = get_service()
    prefs = await asyncio.to_thread(svc.get_preferences, user_id)
    if not prefs:
        return {"user_id": user_id, "persona": "researcher", "theme": "dark", "default_sources": []}
    return prefs


@router.post("/preferences/{user_id}")
async def upsert_preferences(user_id: str, req: UpsertPreferencesRequest):
    """Create or update user preferences."""
    svc = get_service()
    result = await asyncio.to_thread(
        svc.upsert_preferences, user_id, req.persona, req.theme, req.default_sources
    )
    return result
