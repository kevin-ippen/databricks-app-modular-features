"""
File Processing feature module.

Provides file type detection, metadata extraction, schema inference,
UC Volume storage, and FastAPI upload/proxy routes.
"""

from .processor import (
    FileProcessor,
    FileMetadata,
    FileSchema,
    LANGUAGE_EXTENSIONS,
    MIME_TYPE_MAP,
    create_processor,
)
from .storage import (
    FileStorageService,
    UploadedFile,
    SUPPORTED_UPLOAD_TYPES,
)

__all__ = [
    # Processor
    "FileProcessor",
    "FileMetadata",
    "FileSchema",
    "LANGUAGE_EXTENSIONS",
    "MIME_TYPE_MAP",
    "create_processor",
    # Storage
    "FileStorageService",
    "UploadedFile",
    "SUPPORTED_UPLOAD_TYPES",
]
