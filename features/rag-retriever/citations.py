"""
Citation extraction and formatting for RAG responses.

Parses [1], [2]-style references from LLM response text and
formats them for display.
"""

import re
from typing import Any


def extract_citation_refs(text: str) -> list[int]:
    """
    Extract citation reference numbers from response text.

    Finds patterns like [1], [2], [3] in the text.

    Args:
        text: LLM response text with citation markers.

    Returns:
        Sorted list of unique citation reference numbers found.
    """
    matches = re.findall(r'\[(\d+)\]', text)
    refs = sorted(set(int(m) for m in matches))
    return refs


def build_citation_list(
    results: list[dict[str, Any]],
    id_field: str = "doc_id",
    uri_field: str = "doc_uri",
    type_field: str = "doc_type",
    topic_field: str = "topic",
) -> list[dict[str, Any]]:
    """
    Build a citation list from retrieval results.

    Each result is assigned a 1-based reference number matching
    the order it was presented to the LLM.

    Args:
        results: Retrieved documents in presentation order.
        id_field: Key for the document ID.
        uri_field: Key for the document URI/link.
        type_field: Key for the document type.
        topic_field: Key for the topic/title.

    Returns:
        List of citation dicts with keys: ref, doc_id, doc_uri, doc_type, topic, title.
    """
    citations = []
    for i, r in enumerate(results, 1):
        doc_type = r.get(type_field, "document")
        topic = r.get(topic_field, "")
        title = f"{doc_type.replace('_', ' ').title()}: {topic}" if topic else doc_type.replace('_', ' ').title()

        citations.append({
            "ref": i,
            "doc_id": r.get(id_field, ""),
            "doc_uri": r.get(uri_field, ""),
            "doc_type": doc_type,
            "topic": topic,
            "title": title,
        })
    return citations


def format_citations(citations: list[dict[str, Any]], used_refs: list[int] | None = None) -> str:
    """
    Format citations for display in a response.

    Args:
        citations: Citation list from build_citation_list().
        used_refs: Optional list of reference numbers actually used in the text.
                   If provided, only those citations are included.

    Returns:
        Formatted string with one citation per line.
    """
    if not citations:
        return "_No sources_"

    lines = []
    for c in citations:
        ref = c.get("ref", "?")
        if used_refs and ref not in used_refs:
            continue
        title = c.get("title", "Unknown")
        doc_uri = c.get("doc_uri", "")

        if doc_uri:
            lines.append(f"[{ref}] {title} ({doc_uri})")
        else:
            lines.append(f"[{ref}] {title}")

    return "\n".join(lines) if lines else "_No sources_"


def format_inline_citations(text: str, citations: list[dict[str, Any]]) -> str:
    """
    Replace [N] references in text with linked/titled versions.

    Args:
        text: Response text with [N] citation markers.
        citations: Citation list from build_citation_list().

    Returns:
        Text with [N] replaced by [N: Title] for readability.
    """
    citation_map = {c["ref"]: c for c in citations}

    def replace_ref(match):
        ref = int(match.group(1))
        c = citation_map.get(ref)
        if c:
            return f'[{ref}: {c.get("title", "Source")}]'
        return match.group(0)

    return re.sub(r'\[(\d+)\]', replace_ref, text)
