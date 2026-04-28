"""
Structured logging with request correlation and background persistence.

Provides:
- StructuredLogger with request_id correlation across a request lifecycle
- operation() context manager for auto-timing start/duration/success/error
- Background thread that batches writes to Lakebase (or any Postgres)
  via a configurable connection_factory — no hardcoded table names or hosts
- Queue-based non-blocking design: logging never blocks the caller

Log schema:
    timestamp, level, component, request_id, message, extra (JSON),
    error (JSON), duration_ms
"""

import json
import time
import traceback
import threading
import logging
from contextlib import contextmanager
from datetime import datetime, timezone
from queue import Queue, Empty
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── Background writer ─────────────────────────────────────────────────────────

class _BackgroundWriter:
    """
    Batches log entries from a queue and writes them to Postgres/Lakebase
    periodically (every flush_interval_s seconds or when batch_size is reached).
    """

    def __init__(
        self,
        connection_factory: Callable,
        table: str,
        batch_size: int = 50,
        flush_interval_s: float = 10.0,
    ):
        self._connection_factory = connection_factory
        self._table = table
        self._batch_size = batch_size
        self._flush_interval_s = flush_interval_s
        self._queue: Queue = Queue()
        self._started = False
        self._lock = threading.Lock()

    def enqueue(self, entry: dict) -> None:
        """Non-blocking enqueue of a log entry."""
        self._queue.put(entry)
        self._ensure_started()

    def _ensure_started(self) -> None:
        if self._started:
            return
        with self._lock:
            if self._started:
                return
            self._started = True
            thread = threading.Thread(target=self._writer_loop, daemon=True)
            thread.start()

    def _writer_loop(self) -> None:
        batch: List[Dict] = []
        last_flush = time.time()

        while True:
            try:
                # Drain queue into batch
                while len(batch) < self._batch_size:
                    try:
                        entry = self._queue.get_nowait()
                        batch.append(entry)
                    except Empty:
                        break

                # Flush when batch is full or interval elapsed
                now = time.time()
                should_flush = (
                    batch
                    and (len(batch) >= self._batch_size or now - last_flush >= self._flush_interval_s)
                )

                if should_flush:
                    self._flush(batch)
                    batch = []
                    last_flush = time.time()

                # Sleep briefly to avoid busy-waiting
                time.sleep(0.5)

            except Exception as e:
                logger.error("Background log writer error: %s", e)
                time.sleep(2)

    def _flush(self, batch: List[Dict]) -> None:
        """Write a batch of log entries to the database."""
        if not batch:
            return

        try:
            conn = self._connection_factory()
            cursor = conn.cursor()

            insert_sql = f"""
                INSERT INTO {self._table}
                    (timestamp, level, component, request_id, message, extra, error, duration_ms)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """

            rows = []
            for entry in batch:
                rows.append((
                    entry.get("timestamp", datetime.now(timezone.utc).isoformat()),
                    entry.get("level", "INFO"),
                    entry.get("component", "unknown"),
                    entry.get("request_id", ""),
                    (entry.get("message", "") or "")[:2000],
                    json.dumps(entry.get("extra", {}))[:4000],
                    json.dumps(entry["error"])[:4000] if entry.get("error") else None,
                    entry.get("duration_ms"),
                ))

            cursor.executemany(insert_sql, rows)
            conn.commit()
            cursor.close()
            conn.close()

        except Exception as e:
            logger.error(
                "Failed to flush %d log entries to %s: %s",
                len(batch), self._table, e,
            )


# ── Global writer registry ───────────────────────────────────────────────────

_writers: Dict[str, _BackgroundWriter] = {}
_writers_lock = threading.Lock()


def _get_writer(
    connection_factory: Callable,
    table: str,
    batch_size: int,
    flush_interval_s: float,
) -> _BackgroundWriter:
    """Get or create a background writer for the given table."""
    key = f"{id(connection_factory)}:{table}"
    if key not in _writers:
        with _writers_lock:
            if key not in _writers:
                _writers[key] = _BackgroundWriter(
                    connection_factory=connection_factory,
                    table=table,
                    batch_size=batch_size,
                    flush_interval_s=flush_interval_s,
                )
    return _writers[key]


# ── StructuredLogger ──────────────────────────────────────────────────────────

class StructuredLogger:
    """
    Structured logger with request correlation and performance tracking.

    Logs are always printed to stdout as JSON. Optionally persisted to
    a database table via a background writer thread.

    Args:
        component: Component name (e.g., "search_router", "agent", "tts").
        request_id: Correlation ID for tracing a request across components.
                    Auto-generated if not provided.
        connection_factory: Callable that returns a DB-API 2.0 connection.
                            If None, logs are printed only (no persistence).
        table: Fully-qualified table name for log persistence.
        batch_size: Number of entries to batch before flushing.
        flush_interval_s: Max seconds between flushes.
    """

    def __init__(
        self,
        component: str,
        request_id: Optional[str] = None,
        connection_factory: Optional[Callable] = None,
        table: str = "app_logs",
        batch_size: int = 50,
        flush_interval_s: float = 10.0,
    ):
        self.component = component
        self.request_id = request_id or f"req-{int(time.time() * 1000)}"
        self._connection_factory = connection_factory
        self._writer: Optional[_BackgroundWriter] = None

        if connection_factory is not None:
            self._writer = _get_writer(
                connection_factory, table, batch_size, flush_interval_s,
            )

    def _build_entry(
        self,
        level: str,
        message: str,
        extra: Optional[Dict[str, Any]] = None,
        duration_ms: Optional[float] = None,
        error: Optional[Exception] = None,
    ) -> dict:
        entry: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "component": self.component,
            "request_id": self.request_id,
            "message": message,
        }
        if duration_ms is not None:
            entry["duration_ms"] = round(duration_ms, 2)
        if extra:
            entry["extra"] = extra
        if error:
            entry["error"] = {
                "type": type(error).__name__,
                "message": str(error),
                "traceback": traceback.format_exc(),
            }
        return entry

    def _emit(self, entry: dict) -> None:
        """Print to stdout and optionally enqueue for persistence."""
        print(json.dumps(entry))
        if self._writer is not None:
            self._writer.enqueue(entry.copy())

    def debug(self, message: str, **extra: Any) -> None:
        self._emit(self._build_entry("DEBUG", message, extra or None))

    def info(self, message: str, **extra: Any) -> None:
        self._emit(self._build_entry("INFO", message, extra or None))

    def warning(self, message: str, **extra: Any) -> None:
        self._emit(self._build_entry("WARNING", message, extra or None))

    def error(self, message: str, error: Optional[Exception] = None, **extra: Any) -> None:
        self._emit(self._build_entry("ERROR", message, extra or None, error=error))

    def success(self, message: str, duration_ms: Optional[float] = None, **extra: Any) -> None:
        self._emit(self._build_entry("SUCCESS", message, extra or None, duration_ms=duration_ms))

    @contextmanager
    def operation(self, operation_name: str, **context: Any):
        """
        Context manager that auto-logs start/duration/success/error.

        Usage::

            with logger.operation("embed_query", model="gte-large"):
                embedding = embed(text)

        On success, logs "Completed: embed_query" with duration_ms.
        On exception, logs "Failed: embed_query" with error details, then re-raises.
        """
        start = time.time()
        self.info(f"Starting: {operation_name}", **context)
        try:
            yield self
            duration_ms = (time.time() - start) * 1000
            self.success(f"Completed: {operation_name}", duration_ms=duration_ms, **context)
        except Exception as e:
            duration_ms = (time.time() - start) * 1000
            self.error(f"Failed: {operation_name}", error=e, duration_ms=duration_ms, **context)
            raise


# ── Convenience constructors ──────────────────────────────────────────────────

def get_logger(
    component: str,
    request_id: Optional[str] = None,
    connection_factory: Optional[Callable] = None,
    table: str = "app_logs",
) -> StructuredLogger:
    """
    Get a structured logger for a component.

    Args:
        component: Component name (e.g., "search", "agent", "tts").
        request_id: Optional correlation ID.
        connection_factory: Optional DB connection factory for persistence.
        table: Target table name.

    Returns:
        StructuredLogger instance.
    """
    return StructuredLogger(
        component=component,
        request_id=request_id,
        connection_factory=connection_factory,
        table=table,
    )


@contextmanager
def timed_operation(
    log: StructuredLogger,
    operation_name: str,
    **context: Any,
):
    """
    Standalone context manager for timing operations.

    Usage::

        logger = get_logger("my_component")
        with timed_operation(logger, "expensive_work", user_id=123):
            do_expensive_work()
    """
    with log.operation(operation_name, **context):
        yield
