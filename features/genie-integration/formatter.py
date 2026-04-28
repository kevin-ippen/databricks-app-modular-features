"""
Result formatting for Genie query results.

Converts structured GenieResult objects into markdown tables,
chart-ready dicts, and human-readable response strings.
"""

from typing import Any, Dict, List, Optional

from .genie_client import GenieResult


# ---------------------------------------------------------------------------
# Time formatting
# ---------------------------------------------------------------------------

def format_time(ms: float) -> str:
    """Format milliseconds into a human-readable string."""
    if ms < 1000:
        return f"{ms:.0f}ms"
    return f"{ms / 1000:.1f}s"


# ---------------------------------------------------------------------------
# Markdown table
# ---------------------------------------------------------------------------

def format_result_table(
    columns: List[str],
    rows: List[List[Any]],
    max_rows: int = 25,
) -> str:
    """
    Render columns + rows as a markdown table.

    Args:
        columns: Column header names.
        rows: Data rows (list of lists).
        max_rows: Truncate after this many rows.

    Returns:
        Markdown table string.
    """
    if not columns or not rows:
        return ""

    parts: list[str] = []

    # Header
    parts.append("| " + " | ".join(columns) + " |")
    parts.append("|" + "|".join(["---"] * len(columns)) + "|")

    # Rows
    display_rows = rows[:max_rows]
    for row in display_rows:
        formatted_values = []
        for v in row:
            if v is None:
                formatted_values.append("NULL")
            elif isinstance(v, float):
                if abs(v) >= 1_000_000:
                    formatted_values.append(f"{v:,.0f}")
                elif abs(v) >= 1:
                    formatted_values.append(f"{v:,.2f}")
                else:
                    formatted_values.append(f"{v:.4f}")
            else:
                formatted_values.append(str(v))
        parts.append("| " + " | ".join(formatted_values) + " |")

    if len(rows) > max_rows:
        parts.append(f"\n*Showing first {max_rows} of {len(rows)} rows*")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Full Genie response formatting
# ---------------------------------------------------------------------------

def format_genie_response(
    result: GenieResult,
    *,
    include_sql: bool = True,
    max_rows: int = 25,
) -> str:
    """
    Format a GenieResult into a complete markdown response.

    Includes header with space name and timing, optional narrative text,
    a data table, and a collapsible SQL section.

    Args:
        result: GenieResult from GenieClient.ask().
        include_sql: Whether to append the SQL in a <details> block.
        max_rows: Maximum rows in the table.

    Returns:
        Markdown-formatted response string.
    """
    time_str = format_time(result.execution_time_ms)
    parts: list[str] = [f"**{result.space_name}** ({time_str})"]

    # Error case
    if result.error:
        parts.append("")
        parts.append(f"Error: {result.error}")
        return "\n".join(parts)

    # Narrative text
    if result.response_text:
        parts.append("")
        parts.append(result.response_text)

    # Data table
    if result.columns and result.rows:
        parts.append("")
        parts.append(f"**Results:** {len(result.rows)} rows")
        parts.append("")
        parts.append(
            format_result_table(result.columns, result.rows, max_rows=max_rows)
        )

    # SQL query (collapsible)
    if include_sql and result.sql_query:
        parts.append("")
        parts.append("<details>")
        parts.append("<summary>View SQL Query</summary>")
        parts.append("")
        parts.append(f"```sql\n{result.sql_query}\n```")
        parts.append("</details>")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Chart-ready format
# ---------------------------------------------------------------------------

def to_chart_data(result: GenieResult) -> Dict[str, Any]:
    """
    Convert a GenieResult into a chart-friendly dict.

    Returns:
        {
            "columns": ["col_a", "col_b"],
            "data": [{"col_a": val, "col_b": val}, ...],
            "row_count": int,
            "sql": str | None,
        }
    """
    if not result.columns or not result.rows:
        return {"columns": [], "data": [], "row_count": 0, "sql": result.sql_query}

    data = []
    for row in result.rows:
        record = {}
        for idx, col in enumerate(result.columns):
            record[col] = row[idx] if idx < len(row) else None
        data.append(record)

    return {
        "columns": result.columns,
        "data": data,
        "row_count": len(data),
        "sql": result.sql_query,
    }
