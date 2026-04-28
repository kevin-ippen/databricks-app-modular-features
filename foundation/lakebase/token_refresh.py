"""Background token refresh for Lakebase OAuth connections.

Tokens are refreshed every 50 minutes (before 1-hour expiry).
Supports both provisioned Lakebase (database API) and autoscaling Lakebase (postgres API).
"""

import asyncio
import logging
import os
import uuid
from typing import Optional

logger = logging.getLogger(__name__)

# Token refresh state
_current_token: Optional[str] = None
_token_refresh_task: Optional[asyncio.Task] = None
_lakebase_instance_name: Optional[str] = None
_postgres_endpoint: Optional[str] = None

# Token refresh interval (50 minutes - tokens expire after 1 hour)
TOKEN_REFRESH_INTERVAL_SECONDS = 50 * 60


def _has_oauth_credentials() -> bool:
    """Check if OAuth credentials (SP) are configured in environment."""
    return bool(os.environ.get('DATABRICKS_CLIENT_ID') and os.environ.get('DATABRICKS_CLIENT_SECRET'))


def _get_workspace_client():
    """Get Databricks WorkspaceClient for token generation.

    In Databricks Apps, explicitly uses OAuth M2M to avoid conflicts with other auth methods.
    Returns None if not running in a Databricks environment.
    """
    try:
        from databricks.sdk import WorkspaceClient

        if _has_oauth_credentials():
            # Explicitly configure OAuth M2M to prevent auth conflicts
            return WorkspaceClient(
                host=os.environ.get('DATABRICKS_HOST', ''),
                client_id=os.environ.get('DATABRICKS_CLIENT_ID', ''),
                client_secret=os.environ.get('DATABRICKS_CLIENT_SECRET', ''),
            )
        # Development mode - use default SDK auth
        return WorkspaceClient()
    except Exception as e:
        logger.debug(f"Could not create WorkspaceClient: {e}")
        return None


def _generate_lakebase_token(instance_name: str) -> Optional[str]:
    """Generate a fresh OAuth token for Lakebase (provisioned) connection.

    Args:
        instance_name: Lakebase provisioned instance name

    Returns:
        OAuth token string or None if generation fails
    """
    client = _get_workspace_client()
    if not client:
        return None

    try:
        cred = client.database.generate_database_credential(
            request_id=str(uuid.uuid4()),
            instance_names=[instance_name],
        )
        logger.info(f"Generated new Lakebase token for instance: {instance_name}")
        return cred.token
    except Exception as e:
        logger.error(f"Failed to generate Lakebase token: {e}")
        return None


def _generate_postgres_token(endpoint: str) -> Optional[str]:
    """Generate a fresh OAuth token for Lakebase Autoscaling connection.

    Args:
        endpoint: Endpoint resource path, e.g.
            'projects/my-proj/branches/production/endpoints/primary'

    Returns:
        OAuth token string or None if generation fails
    """
    client = _get_workspace_client()
    if not client:
        return None

    try:
        cred = client.postgres.generate_database_credential(endpoint=endpoint)
        logger.info(f"Generated new autoscaling Lakebase token for endpoint: {endpoint}")
        return cred.token
    except Exception as e:
        logger.error(f"Failed to generate autoscaling Lakebase token: {e}")
        return None


async def _token_refresh_loop():
    """Background task to refresh Lakebase OAuth token every 50 minutes."""
    global _current_token, _lakebase_instance_name, _postgres_endpoint

    while True:
        try:
            await asyncio.sleep(TOKEN_REFRESH_INTERVAL_SECONDS)

            if _postgres_endpoint:
                # Autoscaling Lakebase token refresh
                new_token = await asyncio.to_thread(
                    _generate_postgres_token, _postgres_endpoint
                )
                if new_token:
                    _current_token = new_token
                    logger.info("Autoscaling Lakebase token refreshed successfully")
                else:
                    logger.warning("Failed to refresh autoscaling Lakebase token")
            elif _lakebase_instance_name:
                # Provisioned Lakebase token refresh
                new_token = await asyncio.to_thread(
                    _generate_lakebase_token, _lakebase_instance_name
                )
                if new_token:
                    _current_token = new_token
                    logger.info("Lakebase token refreshed successfully")
                else:
                    logger.warning("Failed to refresh Lakebase token")
        except asyncio.CancelledError:
            logger.info("Token refresh task cancelled")
            break
        except Exception as e:
            logger.error(f"Error in token refresh loop: {e}")
            # Continue the loop, will retry on next interval


async def start_token_refresh():
    """Start the background token refresh task."""
    global _token_refresh_task

    if _token_refresh_task is not None:
        logger.warning("Token refresh task already running")
        return

    _token_refresh_task = asyncio.create_task(_token_refresh_loop())
    logger.info("Started Lakebase token refresh background task")


async def stop_token_refresh():
    """Stop the background token refresh task."""
    global _token_refresh_task

    if _token_refresh_task is not None:
        _token_refresh_task.cancel()
        try:
            await _token_refresh_task
        except asyncio.CancelledError:
            pass
        _token_refresh_task = None
        logger.info("Stopped Lakebase token refresh background task")


def get_current_token() -> Optional[str]:
    """Get the current cached token (for use in do_connect event handlers)."""
    return _current_token


def configure(instance_name: Optional[str] = None, postgres_endpoint: Optional[str] = None):
    """Configure the token refresh module with connection details.

    Args:
        instance_name: Lakebase provisioned instance name (for database API)
        postgres_endpoint: Autoscaling Lakebase endpoint path (for postgres API)
    """
    global _lakebase_instance_name, _postgres_endpoint, _current_token

    _lakebase_instance_name = instance_name
    _postgres_endpoint = postgres_endpoint

    # Generate initial token
    if _postgres_endpoint:
        _current_token = _generate_postgres_token(_postgres_endpoint)
    elif _lakebase_instance_name:
        _current_token = _generate_lakebase_token(_lakebase_instance_name)
