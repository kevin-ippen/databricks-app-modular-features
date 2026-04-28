"""
Natural language filter extraction for semantic search.

Extracts structured filters (price caps, quantities, attributes) from
free-text queries using configurable regex patterns.
"""

import re
from typing import Optional, Any


# ── Default filter pattern configuration ──────────────────────────────────────
# Each key maps to a dict with: "pattern" (regex), "type" (int|float|str), "group" (capture group index)

DEFAULT_FILTER_PATTERNS: dict[str, dict[str, Any]] = {
    "max_price": {
        "patterns": [
            r'(?:under|below|max|less than|<|up to)\s*\$?\s*(\d{2,7})',
            r'\$(\d{2,7})\s*(?:per night|/night|a night|nightly|/mo|per month)?',
        ],
        "type": "float",
        "group": 1,
    },
    "min_quantity": {
        "patterns": [
            r'(\d+)\s*(?:bed(?:room)?s?|BR|room|seat|unit)',
            r'(?:sleeps?|fits?|holds?)\s*(\d+)',
        ],
        "type": "int",
        "group": 1,
    },
}


class FilterConfig:
    """
    Configurable filter extraction patterns.

    Args:
        patterns: Dict mapping filter_name -> {patterns: [regex], type: str, group: int}
                  'type' is one of 'int', 'float', 'str'.
                  'group' is the regex capture group index (1-based).
    """

    def __init__(self, patterns: Optional[dict[str, dict[str, Any]]] = None):
        self.patterns = patterns or DEFAULT_FILTER_PATTERNS
        self._compiled: dict[str, list[re.Pattern]] = {}
        self._compile_patterns()

    def _compile_patterns(self):
        for name, cfg in self.patterns.items():
            self._compiled[name] = [
                re.compile(p, re.IGNORECASE)
                for p in cfg.get("patterns", [])
            ]

    def get_compiled(self, name: str) -> list[re.Pattern]:
        return self._compiled.get(name, [])


def extract_filters(
    query: str,
    config: Optional[FilterConfig] = None,
) -> tuple[dict[str, Any], str]:
    """
    Extract structured filters from a natural language query.

    Args:
        query: Raw user query text.
        config: FilterConfig with regex patterns. Uses defaults if None.

    Returns:
        Tuple of (extracted_filters dict, cleaned_query with filter text removed).
        The dict keys match the pattern names from config.
    """
    if config is None:
        config = FilterConfig()

    filters: dict[str, Any] = {}
    cleaned = query

    for name, cfg in config.patterns.items():
        group_idx = cfg.get("group", 1)
        value_type = cfg.get("type", "str")

        for pattern in config.get_compiled(name):
            m = pattern.search(cleaned)
            if m:
                raw_value = m.group(group_idx)
                # Convert type
                if value_type == "int":
                    filters[name] = int(raw_value)
                elif value_type == "float":
                    filters[name] = float(raw_value)
                else:
                    filters[name] = raw_value

                # Remove matched text from query for cleaner embedding
                cleaned = cleaned[:m.start()] + cleaned[m.end():]
                break  # First match wins per filter name

    return filters, cleaned.strip()


def build_vs_filter_dict(filters: dict[str, Any], column_mapping: dict[str, dict]) -> Optional[dict]:
    """
    Build a Databricks Vector Search filter dict from extracted filters.

    Args:
        filters: Extracted filter dict from extract_filters().
        column_mapping: Maps filter_name -> {"column": str, "operator": str}.
                        Operator is one of: EQUAL, LESS_THAN_OR_EQUAL_TO,
                        GREATER_THAN_OR_EQUAL_TO, IN, etc.

    Returns:
        VS filter dict (nested AND/OR), or None if no applicable filters.
    """
    clauses = []

    for filter_name, value in filters.items():
        mapping = column_mapping.get(filter_name)
        if not mapping:
            continue
        col = mapping["column"]
        op = mapping.get("operator", "EQUAL")
        clauses.append({col: {op: value}})

    if not clauses:
        return None
    if len(clauses) == 1:
        return clauses[0]
    return {"AND": clauses}
