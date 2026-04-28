"""
Intent detection for semantic search queries.

Detects user intents (e.g., price-sensitive, family-oriented, privacy-seeking)
from query text using configurable keyword sets. Intents drive re-ranking boosts.
"""

from typing import Optional


# ── Default intent keyword sets ───────────────────────────────────────────────
# Each key is an intent name, value is a set of trigger words.

DEFAULT_INTENT_KEYWORDS: dict[str, set[str]] = {
    "price": {"budget", "cheap", "affordable", "deal", "value", "inexpensive", "bargain", "under", "below"},
    "family": {"family", "families", "kids", "children", "kid-friendly", "child", "toddler", "baby"},
    "privacy": {"private", "privacy", "secluded", "quiet", "peaceful", "remote", "isolated"},
    "couples": {"couple", "couples", "romantic", "honeymoon", "anniversary", "getaway", "retreat"},
    "group": {"group", "groups", "reunion", "bachelor", "bachelorette", "party", "gathering"},
    "luxury": {"luxury", "premium", "upscale", "high-end", "exclusive", "resort", "spa"},
}


def detect_intents(
    query: str,
    intent_keywords: Optional[dict[str, set[str]]] = None,
    substring_intents: Optional[dict[str, list[str]]] = None,
) -> dict[str, float]:
    """
    Detect query intent signals for re-ranking.

    Uses word-level matching against configurable keyword sets.
    Optionally supports substring matching for multi-word phrases.

    Args:
        query: User search query.
        intent_keywords: Dict mapping intent_name -> set of trigger words.
                         Uses DEFAULT_INTENT_KEYWORDS if None.
        substring_intents: Optional dict mapping intent_name -> list of substrings
                           to match anywhere in the query (for multi-word phrases
                           like "lake access" that won't match word-by-word).

    Returns:
        Dict of {intent_name: weight} for detected intents.
        Default weight is 1.0 for any detected intent.
    """
    if intent_keywords is None:
        intent_keywords = DEFAULT_INTENT_KEYWORDS

    words = set(query.lower().split())
    q_lower = query.lower()
    intents: dict[str, float] = {}

    # Word-level matching
    for intent_name, keywords in intent_keywords.items():
        if words & keywords:
            intents[intent_name] = 1.0

    # Substring matching for multi-word phrases
    if substring_intents:
        for intent_name, substrings in substring_intents.items():
            if intent_name not in intents:
                for substr in substrings:
                    if substr.lower() in q_lower:
                        intents[intent_name] = 1.0
                        break

    return intents
