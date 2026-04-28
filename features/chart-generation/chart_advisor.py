"""
Chart Advisor -- LLM-powered chart type recommendation.

Uses a configurable Foundation Model API endpoint to analyze a user's question,
SQL, and result shape, then returns a structured ChartRecommendation.  Falls back
to None on any failure so the caller can use rule-based heuristics instead.

Merges the best of two implementations:
  - Fast structured-JSON advisor (Gemini Flash pattern)
  - Semantic intent-aware advisor (Haiku pattern)

Usage:
    advisor = ChartAdvisor(host="https://...", token="...", model="databricks-claude-haiku-4-5")
    rec = await advisor.recommend(question, columns, sample_rows, sql=sql)
    if rec is not None:
        # use rec.chart_type, rec.x_field, etc.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

VALID_CHART_TYPES = frozenset({
    "line",
    "area",
    "bar",
    "horizontal_bar",
    "stacked_bar",
    "pie",
    "scatter",
    "heatmap",
    "sankey",
    "bump",
    "big_number",
    "table",
})


@dataclass(frozen=True)
class ChartRecommendation:
    """Immutable recommendation returned by the advisor."""

    chart_type: str
    x_field: str
    y_field: str
    series_field: Optional[str] = None
    title: str = ""
    reasoning: str = ""
    format_hint: str = "plain"
    hints: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# System prompt -- deterministic, comprehensive rules
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are a data visualization expert. Given a user's question, the SQL that \
answered it, the result columns, and sample rows, decide the best chart type.

Return ONLY a JSON object with these fields:
{
  "chart_type": "<see list below>",
  "x_field": "<column name for categories / labels / dates>",
  "y_field": "<column name for the numeric metric to plot>",
  "series_field": "<column for multi-series grouping, or null>",
  "format_hint": "currency" | "percentage" | "plain",
  "title": "<short chart title>",
  "reasoning": "<one sentence>"
}

Allowed chart_type values and when to use each:
  line            -- Time series (dates / months / quarters ordered chronologically). Default for time data.
  area            -- Single time series where filled area conveys volume. ONLY for a single series.
  bar             -- Categorical comparison, sorted descending. Default for discrete groups.
  horizontal_bar  -- Like bar, but when category labels are long strings.
  stacked_bar     -- Part-of-whole across categories when you need to show composition per group.
  pie             -- Part-of-whole ONLY when (1) question asks about share/percentage, (2) <=6 items, (3) y column is a percentage. Prefer bar when in doubt.
  scatter         -- Two-measure correlation (e.g. spend vs return, margin vs volume).
  heatmap         -- Hour x day-of-week intensity. ONLY when both hour and day_of_week columns exist.
  sankey          -- State flow. ONLY when old_state / new_state / transitions columns exist.
  bump            -- Rank changes over time. ONLY when question asks about ranking movement.
  big_number      -- Single aggregate value (one row, one or two columns).
  table           -- Fallback for many columns, many rows, or when precision matters.

Rules:
- x_field is ALWAYS the category/label/date column. y_field is ALWAYS the numeric value column.
- IGNORE rank/order/position/row_number columns -- they are not metrics.
- Column names with dollar/revenue/spend/cost/price/sales -> format_hint = "currency".
- Column names with pct/percent/rate/ratio/share -> format_hint = "percentage".
- For x_field prefer human-readable names over IDs.
- Bar charts with >15 categories -> consider "table".
- Data with BOTH positive AND negative values -> always bar or horizontal_bar.
- Multiple numeric columns -> pick the one most relevant to the question as y_field.
- A label column + 1-2 numeric columns should ALWAYS get a chart, never "table".
- For multi-series time data use "line" not "area".

Return ONLY the JSON, no markdown, no explanation."""

# ---------------------------------------------------------------------------
# Advisor class
# ---------------------------------------------------------------------------


class ChartAdvisor:
    """LLM-powered chart recommendation engine.

    Parameters
    ----------
    host : str
        Workspace URL, e.g. ``"https://adb-12345.azuredatabricks.net"``.
    token : str
        Databricks personal access token or OBO token.
    model : str
        Serving endpoint name, e.g. ``"databricks-claude-haiku-4-5"``.
    timeout_s : float
        Total timeout for the LLM call in seconds.
    max_tokens : int
        Max tokens for the LLM response (keep small for speed).
    """

    def __init__(
        self,
        host: str,
        token: str,
        model: str,
        timeout_s: float = 8.0,
        max_tokens: int = 250,
    ) -> None:
        # Strip trailing slash from host
        self.host = host.rstrip("/")
        self.token = token
        self.model = model
        self.timeout_s = timeout_s
        self.max_tokens = max_tokens

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def recommend(
        self,
        question: str,
        columns: list[str],
        sample_rows: list[list],
        sql: str = "",
    ) -> Optional[ChartRecommendation]:
        """Return a chart recommendation, or ``None`` if the call fails.

        Parameters
        ----------
        question : str
            The user's natural-language question.
        columns : list[str]
            Column names from the query result.
        sample_rows : list[list]
            First N rows of data (raw values).
        sql : str, optional
            The SQL query that produced the result.
        """
        user_prompt = self._build_user_prompt(question, columns, sample_rows, sql)
        raw_json = await self._call_llm(user_prompt)
        if raw_json is None:
            return None
        return self._parse_recommendation(raw_json)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _build_user_prompt(
        question: str,
        columns: list[str],
        sample_rows: list[list],
        sql: str,
    ) -> str:
        sample = sample_rows[:5]
        parts = [f'Question: "{question}"']
        if sql:
            parts.append(f"SQL:\n{sql[:600]}")
        parts.append(f"Result columns: {columns}")
        parts.append(
            f"Sample rows (first {len(sample)}):\n"
            f"{json.dumps(sample, default=str)[:1000]}"
        )
        parts.append(f"Total rows returned: {len(sample_rows)}")
        return "\n\n".join(parts)

    async def _call_llm(self, user_prompt: str) -> Optional[str]:
        """Fire the LLM request and return raw content string, or None."""
        url = f"{self.host}/serving-endpoints/{self.model}/invocations"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }
        payload = {
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": self.max_tokens,
            "temperature": 0,
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout_s + 2) as client:
                resp = await asyncio.wait_for(
                    client.post(url, json=payload, headers=headers),
                    timeout=self.timeout_s,
                )
                if resp.status_code != 200:
                    logger.warning(
                        "ChartAdvisor: model %s returned HTTP %d",
                        self.model,
                        resp.status_code,
                    )
                    return None

                data = resp.json()
                raw_content = data["choices"][0]["message"]["content"]

                # Some models return content as a list of parts
                if isinstance(raw_content, list):
                    return "".join(
                        p.get("text", str(p)) if isinstance(p, dict) else str(p)
                        for p in raw_content
                    ).strip()
                return str(raw_content).strip()

        except asyncio.TimeoutError:
            logger.debug("ChartAdvisor: timed out after %.1fs", self.timeout_s)
            return None
        except Exception as exc:
            logger.debug("ChartAdvisor: LLM call failed (%s): %s", type(exc).__name__, exc)
            return None

    @staticmethod
    def _parse_recommendation(raw: str) -> Optional[ChartRecommendation]:
        """Parse raw LLM text into a ChartRecommendation, or None."""
        try:
            content = _extract_json_block(raw)
            rec = json.loads(content)
        except (json.JSONDecodeError, ValueError):
            logger.warning("ChartAdvisor: failed to parse JSON from response")
            return None

        chart_type = rec.get("chart_type")
        x_field = rec.get("x_field")
        y_field = rec.get("y_field")

        if not chart_type or not x_field or not y_field:
            logger.warning("ChartAdvisor: incomplete recommendation: %s", rec)
            return None

        if chart_type not in VALID_CHART_TYPES:
            logger.warning("ChartAdvisor: unknown chart_type '%s'", chart_type)
            return None

        return ChartRecommendation(
            chart_type=chart_type,
            x_field=x_field,
            y_field=y_field,
            series_field=rec.get("series_field") or None,
            title=rec.get("title", ""),
            reasoning=rec.get("reasoning", ""),
            format_hint=rec.get("format_hint", "plain"),
        )


# ---------------------------------------------------------------------------
# JSON extraction helper
# ---------------------------------------------------------------------------


def _extract_json_block(text: str) -> str:
    """Strip markdown fences and locate the JSON object in raw LLM output."""
    text = text.strip()

    # Remove ```json ... ``` wrappers
    if text.startswith("```"):
        first_nl = text.find("\n")
        if first_nl > 0:
            text = text[first_nl + 1:]
        else:
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    # Find the first { ... last }
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("No JSON object found in response")

    return text[start : end + 1]
