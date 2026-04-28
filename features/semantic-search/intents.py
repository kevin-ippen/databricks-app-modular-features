"""
Intent detection for semantic search queries.

Detects user intents (e.g., price-sensitive, family-oriented, luxury-seeking)
from query text using configurable IntentConfig definitions. Detected intents
drive re-ranking boost scores in the search pipeline.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class IntentConfig:
    """
    Configuration for a single detectable search intent.

    Args:
        name: Unique intent identifier (e.g., "price", "family", "luxury").
        keywords: Set of single-word triggers matched against query tokens.
        boost_field: Optional metadata field name used to compute the boost
                     (e.g., "price_discount_pct", "fit_family"). Consumers
                     of detected intents use this to look up per-row scores.
        boost_weight: Maximum boost weight this intent can contribute to
                      the re-ranking formula (0.0-1.0).
        substrings: Optional list of multi-word phrases matched as substrings
                    in the query (e.g., "lake access", "kid-friendly").
    """
    name: str
    keywords: set[str]
    boost_field: str = ""
    boost_weight: float = 0.15
    substrings: list[str] = field(default_factory=list)


# ── Default intent definitions ────────────────────────────────────────────────
# Override with your own list of IntentConfig for domain-specific detection.

DEFAULT_INTENT_CONFIGS: list[IntentConfig] = [
    IntentConfig(
        name="price",
        keywords={"budget", "cheap", "affordable", "deal", "value", "inexpensive", "bargain", "under", "below"},
        boost_field="price_discount_pct",
        boost_weight=0.15,
    ),
    IntentConfig(
        name="family",
        keywords={"family", "families", "kids", "children", "kid-friendly", "child", "toddler", "baby"},
        boost_field="fit_family",
        boost_weight=0.15,
        substrings=["kid friendly", "family friendly"],
    ),
    IntentConfig(
        name="privacy",
        keywords={"private", "privacy", "secluded", "quiet", "peaceful", "remote", "isolated"},
        boost_field="privacy_score",
        boost_weight=0.15,
    ),
    IntentConfig(
        name="couples",
        keywords={"couple", "couples", "romantic", "honeymoon", "anniversary", "getaway", "retreat"},
        boost_field="fit_couples",
        boost_weight=0.15,
    ),
    IntentConfig(
        name="group",
        keywords={"group", "groups", "reunion", "bachelor", "bachelorette", "party", "gathering"},
        boost_field="fit_group",
        boost_weight=0.15,
    ),
    IntentConfig(
        name="luxury",
        keywords={"luxury", "premium", "upscale", "high-end", "exclusive", "resort", "spa"},
        boost_field="quality_tier",
        boost_weight=0.10,
    ),
]


def detect_intents(
    query: str,
    intent_configs: Optional[list[IntentConfig]] = None,
) -> dict[str, float]:
    """
    Detect query intent signals for re-ranking.

    Each detected intent returns its ``boost_weight`` as the score value.
    Undetected intents are omitted from the result dict.

    Args:
        query: User search query.
        intent_configs: List of IntentConfig definitions. Uses DEFAULT_INTENT_CONFIGS if None.

    Returns:
        Dict of {intent_name: boost_score} for every detected intent.
    """
    if intent_configs is None:
        intent_configs = DEFAULT_INTENT_CONFIGS

    words = set(query.lower().split())
    q_lower = query.lower()
    intents: dict[str, float] = {}

    for cfg in intent_configs:
        # Word-level matching
        if words & cfg.keywords:
            intents[cfg.name] = cfg.boost_weight
            continue

        # Substring matching for multi-word phrases
        if cfg.substrings:
            for substr in cfg.substrings:
                if substr.lower() in q_lower:
                    intents[cfg.name] = cfg.boost_weight
                    break

    return intents


def get_intent_boost_fields(
    detected: dict[str, float],
    intent_configs: Optional[list[IntentConfig]] = None,
) -> dict[str, str]:
    """
    Map detected intent names to their boost_field columns.

    Useful when the search pipeline needs to look up per-row metadata
    values for intent-based boosting.

    Args:
        detected: Output of detect_intents().
        intent_configs: Same config list used in detect_intents().

    Returns:
        Dict of {intent_name: boost_field} for detected intents that
        have a non-empty boost_field.
    """
    if intent_configs is None:
        intent_configs = DEFAULT_INTENT_CONFIGS

    config_map = {c.name: c for c in intent_configs}
    result: dict[str, str] = {}
    for intent_name in detected:
        cfg = config_map.get(intent_name)
        if cfg and cfg.boost_field:
            result[intent_name] = cfg.boost_field
    return result
