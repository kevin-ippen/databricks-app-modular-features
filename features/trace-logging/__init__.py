"""
Trace Logging feature module.

Provides structured logging with request correlation, auto-timing
context managers, and background batched persistence to Lakebase.
"""

from .logger import (
    StructuredLogger,
    get_logger,
    timed_operation,
)

__all__ = [
    "StructuredLogger",
    "get_logger",
    "timed_operation",
]
