"""
Research Library feature module.

Provides collections CRUD, annotations, search history tracking,
and user preferences — backed by PostgreSQL (Lakebase).
"""

from .service import ResearchLibraryService
from .router import router, init_service, get_service

__all__ = [
    "ResearchLibraryService",
    "router",
    "init_service",
    "get_service",
]
