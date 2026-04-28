"""Application configuration template for Databricks Apps."""

import os
from typing import Optional
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    app_name: str = "My App"
    debug: bool = False

    # Unity Catalog
    catalog: str = "my_catalog"

    # FMAPI endpoints
    serving_endpoint: str = "databricks-claude-sonnet-4-6"
    haiku_endpoint: str = "databricks-claude-haiku-4-5"

    # Databricks workspace (auto-injected in Apps)
    databricks_host: Optional[str] = None
    databricks_client_id: Optional[str] = None
    databricks_client_secret: Optional[str] = None
    databricks_token: Optional[str] = None  # PAT for local dev

    # SQL Warehouse
    databricks_warehouse_id: Optional[str] = None

    # Genie Space
    genie_space_id: Optional[str] = None

    # Lakebase (auto-injected by Apps when database resource is attached)
    pghost: Optional[str] = None
    pgport: str = "5432"
    pgdatabase: str = "databricks_postgres"
    pguser: Optional[str] = None
    pg_database_instance: Optional[str] = None

    @property
    def pg_connection_string(self) -> Optional[str]:
        if not self.pghost:
            return None
        # PGUSER → DATABRICKS_CLIENT_ID (SP client_id, auto-injected in Apps) → fallback
        user = self.pguser or self.databricks_client_id or "token"
        return f"postgresql://{user}@{self.pghost}:{self.pgport}/{self.pgdatabase}"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
