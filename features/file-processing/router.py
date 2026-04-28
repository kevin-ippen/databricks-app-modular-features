"""
FastAPI routes for file upload, download, and proxy.

Provides:
  POST /files/upload   — upload with optional base64 return (images)
  GET  /files/proxy    — stream files from UC Volumes
  POST /files/prefetch — hint to warm up file access
"""

import base64
import logging
import mimetypes
from pathlib import Path
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Request, UploadFile, File
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from foundation.config import get_settings
from foundation.auth import get_databricks_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/files", tags=["files"])


# ── Request / Response models ─────────────────────────────────────────────────

class FileUploadResponse(BaseModel):
    success: bool
    filename: str
    mime_type: str
    size: int
    base64_data: Optional[str] = None
    volume_path: Optional[str] = None


class PrefetchResponse(BaseModel):
    status: str
    count: int


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/upload", response_model=FileUploadResponse)
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
):
    """
    Upload a file for multimodal chat or document processing.

    For images, returns base64-encoded data for immediate use.
    Supported: jpg, jpeg, png, gif, webp, pdf, txt, md, csv, json.
    """
    try:
        content = await file.read()
        size = len(content)

        max_size = 10 * 1024 * 1024  # 10 MB
        if size > max_size:
            raise HTTPException(
                status_code=413,
                detail=f"File too large. Maximum size is {max_size // (1024 * 1024)}MB",
            )

        mime_type = file.content_type
        if not mime_type:
            mime_type, _ = mimetypes.guess_type(file.filename)
            mime_type = mime_type or "application/octet-stream"

        base64_data = None
        if mime_type.startswith("image/"):
            base64_data = base64.b64encode(content).decode("utf-8")

        logger.info(f"[UPLOAD] File: {file.filename}, Size: {size}, Type: {mime_type}")

        return FileUploadResponse(
            success=True,
            filename=file.filename,
            mime_type=mime_type,
            size=size,
            base64_data=base64_data,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[UPLOAD] Error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")


@router.get("/proxy")
async def proxy_file(
    request: Request,
    path: str,
    page: Optional[int] = None,
):
    """
    Proxy files from UC Volumes for preview.

    Query params:
      - path: UC Volume path (e.g., /Volumes/catalog/schema/volume/file.pdf)
      - page: Optional page number for PDFs
    """
    try:
        if not path.startswith("/Volumes/"):
            raise HTTPException(
                status_code=400,
                detail="Only UC Volume paths are supported",
            )

        token = get_databricks_token(request)

        from databricks.sdk import WorkspaceClient
        wc = WorkspaceClient(token=token)

        mime_type, _ = mimetypes.guess_type(path)
        mime_type = mime_type or "application/octet-stream"

        def file_streamer():
            with wc.files.download(path).contents as f:
                while chunk := f.read(8192):
                    yield chunk

        filename = Path(path).name
        headers = {"Content-Disposition": f'inline; filename="{filename}"'}

        logger.info(f"[PROXY] Serving: {path}")

        return StreamingResponse(
            file_streamer(),
            media_type=mime_type,
            headers=headers,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[PROXY] Error accessing {path}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to access file: {str(e)}")


@router.post("/prefetch", response_model=PrefetchResponse)
async def prefetch_files(
    request: Request,
    paths: List[str],
):
    """
    Prefetch hint for multiple files. Currently a no-op stub
    that can be extended for caching.
    """
    logger.info(f"[PREFETCH] Requested {len(paths)} files")
    return PrefetchResponse(status="acknowledged", count=len(paths))
