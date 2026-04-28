"""
File storage service for Unity Catalog Volumes.

Upload, download, list, and delete files via the Databricks SDK Files API.
Volume path is configurable via constructor or FILE_VOLUME_PATH env var.
"""

import asyncio
import os
import uuid
import logging
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Any, Optional

from databricks.sdk import WorkspaceClient

logger = logging.getLogger(__name__)


# ── Supported upload types ────────────────────────────────────────────────────

SUPPORTED_UPLOAD_TYPES: dict[str, str] = {
    # Documents
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/msword": ".doc",
    "text/plain": ".txt",
    "text/csv": ".csv",
    "application/json": ".json",
    # Spreadsheets
    "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    # Images
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
}


@dataclass
class UploadedFile:
    """Represents a file uploaded to UC Volumes."""
    file_id: str
    session_id: str
    user_id: Optional[str]
    filename: str
    file_type: str
    file_size_bytes: int
    volume_path: str
    upload_timestamp: str
    processed: bool = False
    vector_indexed: bool = False
    metadata: Optional[dict[str, str]] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class FileStorageService:
    """
    Service for storing files in Unity Catalog Volumes.

    Args:
        volume_path: Base UC Volume path (e.g., /Volumes/catalog/schema/volume).
                     Falls back to FILE_VOLUME_PATH env var.
        artifacts_path: Optional separate volume for agent artifacts.
                        Falls back to FILE_ARTIFACTS_PATH env var.
        workspace_client: Optional WorkspaceClient. Created with defaults if not provided.
    """

    def __init__(
        self,
        volume_path: Optional[str] = None,
        artifacts_path: Optional[str] = None,
        workspace_client: Optional[WorkspaceClient] = None,
    ):
        self._client = workspace_client
        self._uploads_base = (
            volume_path
            or os.environ.get("FILE_VOLUME_PATH")
            or "/Volumes/main/default/uploaded_files"
        )
        self._artifacts_base = (
            artifacts_path
            or os.environ.get("FILE_ARTIFACTS_PATH")
            or f"{self._uploads_base}_artifacts"
        )

    @property
    def client(self) -> WorkspaceClient:
        if self._client is None:
            self._client = WorkspaceClient()
        return self._client

    def upload_file(
        self,
        file_content: bytes,
        filename: str,
        session_id: str,
        user_id: Optional[str] = None,
        mime_type: Optional[str] = None,
        metadata: Optional[dict[str, str]] = None,
    ) -> UploadedFile:
        """Upload a file to UC Volumes."""
        file_id = str(uuid.uuid4())
        ext = os.path.splitext(filename)[1].lower()
        if not ext and mime_type:
            ext = SUPPORTED_UPLOAD_TYPES.get(mime_type, "")

        safe_filename = f"{file_id}{ext}"
        volume_path = f"{self._uploads_base}/{session_id}/{safe_filename}"

        try:
            self.client.files.upload(
                file_path=volume_path,
                contents=file_content,
                overwrite=True,
            )
            logger.info(f"Uploaded file to: {volume_path}")
        except Exception as e:
            logger.error(f"Failed to upload file: {e}")
            raise

        return UploadedFile(
            file_id=file_id,
            session_id=session_id,
            user_id=user_id,
            filename=filename,
            file_type=mime_type or ext,
            file_size_bytes=len(file_content),
            volume_path=volume_path,
            upload_timestamp=datetime.utcnow().isoformat(),
            processed=False,
            vector_indexed=False,
            metadata=metadata,
        )

    async def upload_file_async(
        self,
        file_content: bytes,
        filename: str,
        session_id: str,
        user_id: Optional[str] = None,
        mime_type: Optional[str] = None,
        metadata: Optional[dict[str, str]] = None,
    ) -> UploadedFile:
        """Async wrapper — runs sync upload in a thread pool."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.upload_file(
                file_content=file_content,
                filename=filename,
                session_id=session_id,
                user_id=user_id,
                mime_type=mime_type,
                metadata=metadata,
            ),
        )

    def download_file(self, volume_path: str) -> bytes:
        """Download a file from UC Volumes."""
        response = self.client.files.download(file_path=volume_path)
        return response.contents.read()

    def list_session_files(self, session_id: str) -> list[str]:
        """List all files for a session."""
        session_path = f"{self._uploads_base}/{session_id}"
        try:
            files = self.client.files.list_directory_contents(directory_path=session_path)
            return [f.path for f in files if not f.is_directory]
        except Exception:
            return []

    def delete_file(self, volume_path: str) -> bool:
        """Delete a file from UC Volumes."""
        try:
            self.client.files.delete(file_path=volume_path)
            return True
        except Exception as e:
            logger.error(f"Failed to delete file: {e}")
            return False

    def save_artifact(
        self,
        content: bytes,
        artifact_type: str,
        session_id: str,
        filename: str,
    ) -> str:
        """Save an agent-generated artifact. Returns volume path."""
        volume_path = f"{self._artifacts_base}/{artifact_type}/{session_id}/{filename}"
        self.client.files.upload(
            file_path=volume_path,
            contents=content,
            overwrite=True,
        )
        return volume_path
