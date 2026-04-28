"""
Natural language filter extraction for semantic search.

Provides a declarative FilterField/FilterRegistry system for extracting
structured filters from free-text queries using regex patterns, plus a
generic fuzzy text matching utility.
"""

import re
from dataclasses import dataclass, field
from difflib import get_close_matches
from typing import Any, Optional


# ── Declarative filter definitions ────────────────────────────────────────────

@dataclass
class FilterField:
    """
    A single extractable filter.

    Args:
        name: Unique key for this filter (e.g., "max_price", "min_bedrooms").
        field_type: One of "numeric_max", "numeric_min", "enum", "text_match", "boolean".
        patterns: Regex patterns (with capture groups) to extract a value from NL text.
        column: The Vector Search metadata column this filter maps to.
        operator: VS filter operator. Defaults are inferred from field_type:
                  numeric_max -> LESS_THAN_OR_EQUAL_TO
                  numeric_min -> GREATER_THAN_OR_EQUAL_TO
                  enum        -> EQUAL
                  text_match  -> EQUAL
                  boolean     -> EQUAL
        group: Regex capture group index (1-based). Default 1.
    """
    name: str
    field_type: str  # "numeric_max", "numeric_min", "enum", "text_match", "boolean"
    patterns: list[str]
    column: str
    operator: str = ""
    group: int = 1

    def __post_init__(self):
        if not self.operator:
            self.operator = _DEFAULT_OPERATORS.get(self.field_type, "EQUAL")


_DEFAULT_OPERATORS = {
    "numeric_max": "LESS_THAN_OR_EQUAL_TO",
    "numeric_min": "GREATER_THAN_OR_EQUAL_TO",
    "enum": "EQUAL",
    "text_match": "EQUAL",
    "boolean": "EQUAL",
}

_CAST_MAP = {
    "numeric_max": float,
    "numeric_min": int,
    "enum": str,
    "text_match": str,
    "boolean": lambda v: v.lower() in ("true", "yes", "1", "y"),
}


@dataclass
class FilterRegistry:
    """
    Holds a list of FilterField definitions and their compiled regexes.

    Example usage::

        registry = FilterRegistry(fields=[
            FilterField(
                name="max_price",
                field_type="numeric_max",
                patterns=[
                    r'(?:under|below|max|less than|<|up to)\\s*\\$?\\s*(\\d{2,7})',
                    r'\\$(\\d{2,7})\\s*(?:per night|/night|a night)?',
                ],
                column="price_per_night",
            ),
            FilterField(
                name="min_bedrooms",
                field_type="numeric_min",
                patterns=[r'(\\d+)\\s*(?:bed(?:room)?s?|BR)'],
                column="bedrooms",
            ),
        ])
        filters, cleaned = extract_filters("3BR under $300", registry)
        # filters == {"max_price": 300.0, "min_bedrooms": 3}
    """
    fields: list[FilterField] = field(default_factory=list)

    def __post_init__(self):
        self._compiled: dict[str, list[re.Pattern]] = {}
        for f in self.fields:
            self._compiled[f.name] = [
                re.compile(p, re.IGNORECASE) for p in f.patterns
            ]

    def get_compiled(self, name: str) -> list[re.Pattern]:
        return self._compiled.get(name, [])

    def get_field(self, name: str) -> Optional[FilterField]:
        for f in self.fields:
            if f.name == name:
                return f
        return None


# ── Default registry (generic examples) ──────────────────────────────────────
# Override with your own FilterRegistry for domain-specific extraction.

DEFAULT_REGISTRY = FilterRegistry(fields=[
    # Example: price cap — "under $300", "less than 500", "$200/night"
    FilterField(
        name="max_price",
        field_type="numeric_max",
        patterns=[
            r'(?:under|below|max|less than|<|up to)\s*\$?\s*(\d{2,7})',
            r'\$(\d{2,7})\s*(?:per night|/night|a night|nightly|/mo|per month)?',
        ],
        column="price",
    ),
    # Example: minimum quantity — "3 bedrooms", "sleeps 8"
    FilterField(
        name="min_quantity",
        field_type="numeric_min",
        patterns=[
            r'(\d+)\s*(?:bed(?:room)?s?|BR|room|seat|unit)',
            r'(?:sleeps?|fits?|holds?)\s*(\d+)',
        ],
        column="quantity",
    ),
])


# ── Core extraction function ─────────────────────────────────────────────────

def extract_filters(
    query: str,
    registry: Optional[FilterRegistry] = None,
) -> tuple[dict[str, Any], str]:
    """
    Extract structured filters from a natural language query.

    Runs all patterns from the registry against the query text.
    First match wins per filter field. Matched text is removed from
    the returned cleaned query (better for embedding).

    Args:
        query: Raw user query text.
        registry: FilterRegistry with field definitions. Uses DEFAULT_REGISTRY if None.

    Returns:
        Tuple of (extracted_filters dict, cleaned_query).
        Dict keys are the FilterField.name values.
    """
    if registry is None:
        registry = DEFAULT_REGISTRY

    filters: dict[str, Any] = {}
    cleaned = query

    for fld in registry.fields:
        cast_fn = _CAST_MAP.get(fld.field_type, str)

        for pattern in registry.get_compiled(fld.name):
            m = pattern.search(cleaned)
            if m:
                raw_value = m.group(fld.group)
                try:
                    filters[fld.name] = cast_fn(raw_value)
                except (ValueError, TypeError):
                    filters[fld.name] = raw_value

                # Remove matched span from query for cleaner embedding
                cleaned = cleaned[:m.start()] + cleaned[m.end():]
                break  # first match wins per field

    return filters, cleaned.strip()


# ── VS filter builder ────────────────────────────────────────────────────────

def build_vs_filter_dict(
    filters: dict[str, Any],
    registry: Optional[FilterRegistry] = None,
) -> Optional[dict]:
    """
    Build a Databricks Vector Search filter dict from extracted filters.

    Uses the FilterField.column and FilterField.operator from the registry
    to map extracted values into VS filter syntax.

    Args:
        filters: Dict of {field_name: value} from extract_filters().
        registry: FilterRegistry that defines column mappings.

    Returns:
        VS filter dict (nested AND/OR), or None if no applicable filters.
    """
    if registry is None:
        registry = DEFAULT_REGISTRY

    clauses = []
    for filter_name, value in filters.items():
        fld = registry.get_field(filter_name)
        if not fld:
            continue
        clauses.append({fld.column: {fld.operator: value}})

    if not clauses:
        return None
    if len(clauses) == 1:
        return clauses[0]
    return {"AND": clauses}


# ── Fuzzy text matching utility ──────────────────────────────────────────────

def fuzzy_match(
    query: str,
    candidates: list[str],
    cutoff: float = 0.7,
    max_ngram: int = 3,
) -> Optional[str]:
    """
    Fuzzy-match a canonical name from query text against a candidate list.

    Tries exact substring first, then n-gram fuzzy matching via difflib.

    Args:
        query: User query text to search within.
        candidates: List of canonical names to match against.
        cutoff: Minimum similarity ratio for fuzzy matching (0.0-1.0).
        max_ngram: Maximum word n-gram size to try (default 3).

    Returns:
        Best matching candidate string, or None if no match found.

    Example::

        lakes = ["Lake Michigan", "Torch Lake", "Crystal Lake"]
        fuzzy_match("cabin on torch lake area", lakes)  # -> "Torch Lake"
    """
    if not candidates:
        return None

    text_lower = query.lower()
    candidates_lower = [c.lower() for c in candidates]

    # Pass 1: exact substring match (case-insensitive)
    for i, cl in enumerate(candidates_lower):
        if cl in text_lower:
            return candidates[i]

    # Pass 2: n-gram fuzzy matching
    words = text_lower.split()
    for i in range(len(words)):
        for length in range(max_ngram, 0, -1):  # longest ngram first
            if i + length > len(words):
                continue
            candidate_phrase = " ".join(words[i:i + length])
            matches = get_close_matches(
                candidate_phrase, candidates_lower, n=1, cutoff=cutoff,
            )
            if matches:
                idx = candidates_lower.index(matches[0])
                return candidates[idx]

    return None
