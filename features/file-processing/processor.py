"""
File processor — metadata extraction, type detection, schema inference.

Supports PDF, CSV, Excel, JSON, and code files. Self-contained with
no singleton pattern; instantiate directly or use create_processor().
"""

import io
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class FileMetadata:
    """Metadata extracted from a file."""
    filename: str
    file_type: str
    mime_type: str
    size_bytes: int
    encoding: Optional[str] = None
    line_count: Optional[int] = None
    # Structured data
    columns: Optional[list[str]] = None
    row_count: Optional[int] = None
    # Code files
    language: Optional[str] = None
    # Documents
    page_count: Optional[int] = None
    title: Optional[str] = None
    author: Optional[str] = None
    # General
    preview_text: Optional[str] = None
    extracted_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())


@dataclass
class FileSchema:
    """Schema information for structured data files."""
    columns: list[dict[str, Any]]  # [{name, type, nullable, sample_values}]
    row_count: int
    has_header: bool = True


# ── Language and MIME maps ────────────────────────────────────────────────────

LANGUAGE_EXTENSIONS: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".java": "java",
    ".cpp": "cpp",
    ".c": "c",
    ".h": "c",
    ".cs": "csharp",
    ".go": "go",
    ".rs": "rust",
    ".rb": "ruby",
    ".php": "php",
    ".swift": "swift",
    ".kt": "kotlin",
    ".scala": "scala",
    ".r": "r",
    ".sql": "sql",
    ".sh": "bash",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".xml": "xml",
    ".html": "html",
    ".css": "css",
    ".md": "markdown",
    ".toml": "toml",
}

MIME_TYPE_MAP: dict[str, str] = {
    "application/pdf": "pdf",
    "text/csv": "csv",
    "application/json": "json",
    "application/vnd.ms-excel": "excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "excel",
    "text/plain": "text",
    "text/markdown": "markdown",
    "text/x-python": "python",
    "application/javascript": "javascript",
    "application/xml": "xml",
    "text/xml": "xml",
    "image/png": "image",
    "image/jpeg": "image",
    "image/gif": "image",
    "image/webp": "image",
}


# ── FileProcessor class ──────────────────────────────────────────────────────

class FileProcessor:
    """
    Service for processing and analyzing uploaded files.

    Extracts metadata, detects schemas, and prepares files for
    vector indexing or preview.
    """

    def detect_file_type(self, filename: str, mime_type: Optional[str] = None) -> str:
        """
        Detect file type from filename and MIME type.

        Returns file type string (e.g., 'python', 'csv', 'pdf').
        """
        ext = os.path.splitext(filename.lower())[1]
        if ext in LANGUAGE_EXTENSIONS:
            return LANGUAGE_EXTENSIONS[ext]
        if mime_type and mime_type in MIME_TYPE_MAP:
            return MIME_TYPE_MAP[mime_type]
        ext_map = {
            ".pdf": "pdf", ".csv": "csv", ".json": "json",
            ".xlsx": "excel", ".xls": "excel", ".txt": "text", ".md": "markdown",
        }
        return ext_map.get(ext, "unknown")

    def detect_language(self, filename: str) -> Optional[str]:
        """Detect programming language from filename."""
        ext = os.path.splitext(filename.lower())[1]
        return LANGUAGE_EXTENSIONS.get(ext)

    def extract_metadata(
        self,
        content: bytes,
        filename: str,
        mime_type: Optional[str] = None,
    ) -> FileMetadata:
        """Extract metadata from file content."""
        file_type = self.detect_file_type(filename, mime_type)
        metadata = FileMetadata(
            filename=filename,
            file_type=file_type,
            mime_type=mime_type or "application/octet-stream",
            size_bytes=len(content),
        )

        try:
            # Text-based files
            if file_type in ("text", "markdown", "csv", "json", "yaml", "xml") or \
               file_type in LANGUAGE_EXTENSIONS.values():
                text = self._decode_text(content)
                if text:
                    metadata.line_count = len(text.split("\n"))
                    metadata.encoding = "utf-8"
                    metadata.preview_text = text[:1000]
                    if file_type in LANGUAGE_EXTENSIONS.values():
                        metadata.language = file_type

            # CSV schema
            if file_type == "csv":
                schema = self._extract_csv_schema(content)
                if schema:
                    metadata.columns = [c["name"] for c in schema.columns]
                    metadata.row_count = schema.row_count

            # JSON structure
            if file_type == "json":
                try:
                    text = self._decode_text(content)
                    data = json.loads(text)
                    if isinstance(data, list):
                        metadata.row_count = len(data)
                        if data and isinstance(data[0], dict):
                            metadata.columns = list(data[0].keys())
                    elif isinstance(data, dict):
                        metadata.columns = list(data.keys())
                except json.JSONDecodeError:
                    pass

            # PDF metadata
            if file_type == "pdf":
                pdf_meta = self._extract_pdf_metadata(content)
                if pdf_meta:
                    metadata.page_count = pdf_meta.get("page_count")
                    metadata.title = pdf_meta.get("title")
                    metadata.author = pdf_meta.get("author")

        except Exception as e:
            logger.warning(f"Error extracting metadata from {filename}: {e}")

        return metadata

    def extract_text(
        self,
        content: bytes,
        filename: str,
        max_chars: int = 50000,
    ) -> Optional[str]:
        """Extract text content from a file for indexing."""
        file_type = self.detect_file_type(filename)
        try:
            if file_type in ("text", "markdown", "csv", "json", "yaml", "xml") or \
               file_type in LANGUAGE_EXTENSIONS.values():
                text = self._decode_text(content)
                return text[:max_chars] if text else None
            if file_type == "pdf":
                return self._extract_pdf_text(content, max_chars)
        except Exception as e:
            logger.warning(f"Error extracting text from {filename}: {e}")
        return None

    def get_file_schema(self, content: bytes, filename: str) -> Optional[FileSchema]:
        """Get schema information for structured data files."""
        file_type = self.detect_file_type(filename)
        if file_type == "csv":
            return self._extract_csv_schema(content)
        if file_type == "json":
            try:
                text = self._decode_text(content)
                data = json.loads(text)
                if isinstance(data, list) and data and isinstance(data[0], dict):
                    columns = [
                        {
                            "name": key,
                            "type": type(value).__name__,
                            "nullable": True,
                            "sample_values": [str(row.get(key)) for row in data[:5]],
                        }
                        for key, value in data[0].items()
                    ]
                    return FileSchema(columns=columns, row_count=len(data), has_header=True)
            except (json.JSONDecodeError, Exception):
                pass
        return None

    # ── Private helpers ───────────────────────────────────────────────────────

    def _decode_text(self, content: bytes, encodings: Optional[list[str]] = None) -> Optional[str]:
        for enc in (encodings or ["utf-8", "utf-16", "latin-1", "cp1252"]):
            try:
                return content.decode(enc)
            except (UnicodeDecodeError, LookupError):
                continue
        return None

    def _extract_csv_schema(self, content: bytes) -> Optional[FileSchema]:
        try:
            text = self._decode_text(content)
            if not text:
                return None
            lines = text.strip().split("\n")
            if not lines:
                return None

            def parse_line(line: str) -> list[str]:
                result, current, in_quotes = [], "", False
                for char in line:
                    if char == '"':
                        in_quotes = not in_quotes
                    elif char == "," and not in_quotes:
                        result.append(current.strip().strip('"'))
                        current = ""
                    else:
                        current += char
                result.append(current.strip().strip('"'))
                return result

            headers = parse_line(lines[0])
            sample_rows = [parse_line(line) for line in lines[1:min(101, len(lines))]]

            columns = []
            for i, header in enumerate(headers):
                col_values = [row[i] if i < len(row) else "" for row in sample_rows]
                columns.append({
                    "name": header,
                    "type": self._detect_column_type(col_values),
                    "nullable": any(v.strip() == "" for v in col_values),
                    "sample_values": col_values[:5],
                })

            return FileSchema(columns=columns, row_count=len(lines) - 1, has_header=True)
        except Exception as e:
            logger.warning(f"Error extracting CSV schema: {e}")
            return None

    def _detect_column_type(self, values: list[str]) -> str:
        non_empty = [v for v in values if v.strip()]
        if not non_empty:
            return "string"

        numeric_count = sum(1 for v in non_empty if self._is_numeric(v))
        if numeric_count / len(non_empty) > 0.8:
            int_count = sum(1 for v in non_empty if self._is_integer(v))
            return "integer" if int_count / len(non_empty) > 0.8 else "float"

        bool_values = {"true", "false", "yes", "no", "1", "0"}
        if sum(1 for v in non_empty if v.lower() in bool_values) / len(non_empty) > 0.8:
            return "boolean"

        if sum(1 for v in non_empty if self._looks_like_date(v)) / len(non_empty) > 0.8:
            return "date"

        return "string"

    @staticmethod
    def _is_numeric(value: str) -> bool:
        try:
            float(value.replace(",", ""))
            return True
        except ValueError:
            return False

    @staticmethod
    def _is_integer(value: str) -> bool:
        try:
            val = float(value.replace(",", ""))
            return val == int(val)
        except ValueError:
            return False

    @staticmethod
    def _looks_like_date(value: str) -> bool:
        if not any(sep in value for sep in ["-", "/", "."]):
            return False
        parts = value.replace("/", "-").replace(".", "-").split("-")
        if len(parts) < 2:
            return False
        try:
            nums = [int(p) for p in parts if p.isdigit()]
            return len(nums) >= 2
        except ValueError:
            return False

    def _extract_pdf_metadata(self, content: bytes) -> Optional[dict[str, Any]]:
        try:
            try:
                from pypdf import PdfReader
                reader = PdfReader(io.BytesIO(content))
                info = reader.metadata
                return {
                    "page_count": len(reader.pages),
                    "title": info.get("/Title") if info else None,
                    "author": info.get("/Author") if info else None,
                }
            except ImportError:
                text = content.decode("latin-1", errors="ignore")
                page_count = text.count("/Type /Page") or text.count("/Type/Page")
                return {"page_count": max(1, page_count)}
        except Exception as e:
            logger.warning(f"Error extracting PDF metadata: {e}")
            return None

    def _extract_pdf_text(self, content: bytes, max_chars: int) -> Optional[str]:
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(content))
            text_parts, total = [], 0
            for page in reader.pages:
                page_text = page.extract_text() or ""
                text_parts.append(page_text)
                total += len(page_text)
                if total >= max_chars:
                    break
            return "\n\n".join(text_parts)[:max_chars]
        except ImportError:
            logger.warning("pypdf not installed, cannot extract PDF text")
            return None
        except Exception as e:
            logger.warning(f"Error extracting PDF text: {e}")
            return None


def create_processor() -> FileProcessor:
    """Factory function to create a FileProcessor instance."""
    return FileProcessor()
