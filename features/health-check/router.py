"""Health check endpoint for Databricks Apps."""
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class HealthResponse(BaseModel):
    status: str = "healthy"
    app_name: str = ""
    version: str = ""
    timestamp: str = ""
    checks: dict = {}


def create_health_router(
    app_name: str = "My App",
    version: str = "0.1.0",
    checks: dict[str, callable] | None = None,
) -> APIRouter:
    """Create a health check router with optional dependency checks.

    Args:
        app_name: Application name for the response.
        version: Application version.
        checks: Optional dict of {name: callable} where each callable returns
                True (healthy) or raises an exception. Examples:
                {"lakebase": lambda: test_db_connection(),
                 "fmapi": lambda: test_endpoint_ping()}
    """
    router = APIRouter(tags=["health"])
    _checks = checks or {}

    @router.get("/health", response_model=HealthResponse)
    async def health():
        check_results = {}
        overall_healthy = True

        for name, check_fn in _checks.items():
            try:
                result = check_fn()
                if hasattr(result, "__await__"):
                    result = await result
                check_results[name] = "ok"
            except Exception as e:
                check_results[name] = f"error: {e}"
                overall_healthy = False
                logger.warning(f"Health check '{name}' failed: {e}")

        return HealthResponse(
            status="healthy" if overall_healthy else "degraded",
            app_name=app_name,
            version=version,
            timestamp=datetime.now(timezone.utc).isoformat(),
            checks=check_results,
        )

    return router
