"""
Genie Integration feature — configurable Databricks Genie space client.

Provides a reusable client for routing questions to Genie spaces,
polling for results, and formatting responses as markdown tables.
"""

from .genie_client import GenieClient, SpaceConfig, GenieResult
from .formatter import format_genie_response, format_result_table, format_time

__all__ = [
    "GenieClient",
    "SpaceConfig",
    "GenieResult",
    "format_genie_response",
    "format_result_table",
    "format_time",
]
