import logging
from foundation.config import settings
from databricks.sdk import WorkspaceClient
from databricks.sdk.core import Config
from pydantic import BaseModel, field_validator
from threading import Lock
from typing import Optional
from datetime import datetime, timedelta, timezone
import uuid

logger = logging.getLogger(__name__)


class Credential(BaseModel):
    token: str
    expiration_time: datetime

    @field_validator("expiration_time")
    @classmethod
    def _tz_aware_datetime(cls, v: datetime) -> datetime:
        return v if v.tzinfo else v.astimezone(timezone.utc)

    def valid_for(self) -> timedelta:
        return self.expiration_time - datetime.now(timezone.utc)


class LakebaseCredentialProvider:
    """
    Provides database credentials for Lakebase PostgreSQL.

    In Databricks Apps, PGHOST is set but no PGPASSWORD.
    Credentials must be generated via SDK using the instance name.
    Instance name is derived from PGHOST: instance-{uid}.database.azuredatabricks.net
    """

    def __init__(self):
        self.lock = Lock()
        self._cached: Optional[Credential] = None
        self._instance_name: Optional[str] = None

    def _client(self) -> WorkspaceClient:
        return WorkspaceClient()

    def _get_instance_name(self) -> str:
        """Get instance name from PGHOST or explicit config."""
        if self._instance_name:
            return self._instance_name

        # If explicit instance name is configured, use it
        if settings.pg_database_instance:
            self._instance_name = settings.pg_database_instance
            return self._instance_name

        # Extract instance UID from PGHOST and look up instance name
        # PGHOST format: instance-{uid}.database.azuredatabricks.net
        if settings.pghost:
            try:
                # Extract UID from hostname
                hostname = settings.pghost
                if hostname.startswith("instance-"):
                    uid = hostname.split(".")[0].replace("instance-", "")
                    logger.debug(f"Extracted instance UID from PGHOST: {uid}")

                    # Look up instance by UID
                    w = self._client()
                    instance = w.database.find_database_instance_by_uid(uid=uid)
                    self._instance_name = instance.name
                    logger.info(f"Resolved Lakebase instance: {self._instance_name}")
                    return self._instance_name
            except Exception as e:
                logger.warning(f"Failed to resolve instance name from PGHOST: {e}")

        raise ValueError("Cannot determine Lakebase instance. Set PG_DATABASE_INSTANCE or ensure PGHOST is set.")

    def get_credential(self) -> Credential:
        with self.lock:
            # Check if we have a valid cached credential
            if self._cached and self._cached.valid_for() > timedelta(minutes=1):
                return self._cached

            # Generate credentials via SDK
            instance_name = self._get_instance_name()
            logger.debug(f"Generating credential for instance: {instance_name}")

            w = self._client()
            request_id = str(uuid.uuid4())
            cred = w.database.generate_database_credential(
                request_id=request_id, instance_names=[instance_name]
            )
            self._cached = Credential(token=cred.token, expiration_time=cred.expiration_time)
            return self._cached

    def invalidate(self) -> None:
        with self.lock:
            self._cached = None
            self._instance_name = None  # Also clear cached instance name
