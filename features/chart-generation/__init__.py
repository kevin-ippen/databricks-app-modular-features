"""
chart-generation feature -- Vega-Lite spec compilation and LLM-powered chart advice.

Public API:
    ChartAdvisor          -- async LLM chart recommender
    ChartRecommendation   -- dataclass returned by ChartAdvisor.recommend()
    VALID_CHART_TYPES     -- frozenset of supported chart type strings
"""

from .chart_advisor import ChartAdvisor, ChartRecommendation, VALID_CHART_TYPES

__all__ = [
    "ChartAdvisor",
    "ChartRecommendation",
    "VALID_CHART_TYPES",
]
