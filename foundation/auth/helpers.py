"""Authentication helpers for Databricks Apps (OBO + PAT + SP fallback)."""

import os
from typing import Optional
from fastapi import Request
from databricks.sdk import WorkspaceClient
from openai import AsyncOpenAI


def get_user_token(request: Request) -> Optional[str]:
    return request.headers.get("x-forwarded-access-token")


def get_user_email(request: Request) -> Optional[str]:
    return request.headers.get("x-forwarded-email")


def get_user_id(request: Request) -> str:
    user_id = request.headers.get("x-forwarded-email")
    if user_id:
        return user_id
    user_id = request.headers.get("x-forwarded-user")
    if user_id:
        return user_id
    return "anonymous"


def get_app_token() -> str:
    wc = WorkspaceClient()
    headers = wc.config.authenticate()
    return headers["Authorization"].split(" ", 1)[1]


def get_databricks_token(request: Optional[Request] = None) -> str:
    """OBO → PAT → SP fallback."""
    if request:
        token = get_user_token(request)
        if token:
            return token
    pat = os.environ.get("DATABRICKS_TOKEN")
    if pat:
        return pat
    return get_app_token()


def get_databricks_host() -> str:
    host = os.environ.get("DATABRICKS_HOST", "").rstrip("/")
    if not host:
        try:
            wc = WorkspaceClient()
            host = wc.config.host.rstrip("/")
        except Exception:
            raise ValueError("DATABRICKS_HOST environment variable required")
    if host and not host.startswith(("http://", "https://")):
        host = f"https://{host}"
    return host


def get_async_openai_client(token: str) -> AsyncOpenAI:
    host = get_databricks_host()
    return AsyncOpenAI(api_key=token, base_url=f"{host}/serving-endpoints")
