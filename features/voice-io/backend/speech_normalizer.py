"""
Speech Normalizer for Analyst-Grade TTS

Transforms agent/Genie output text into speech-optimized narration:
- Number normalization ($12,543,210 -> "about 12.5 million dollars")
- Acronym expansion (QoQ -> "quarter over quarter")
- Table/code elision
- Smart chunking at sentence boundaries
- Audience-aware rounding (exec/business/technical)
"""

import re
import math
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional


# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

NUM_RE = re.compile(
    r"""
    (?P<prefix>[$\u20ac\u00a3])?
    (?P<num>
      (?:\d{1,3}(?:,\d{3})+|\d+)   # 1,234 or 1234
      (?:\.\d+)?                     # .56
      (?:[eE][+-]?\d+)?              # e-4
    )
    (?P<suffix>%|bps|bp)?
    """,
    re.VERBOSE,
)

ACRONYM_RE = re.compile(r"\b[A-Z]{2,6}\b")

TABLE_RE = re.compile(r"(?:^\|.*\|$\n?){2,}", re.MULTILINE)

CODE_BLOCK_RE = re.compile(r"```[\s\S]*?```")

MARKDOWN_RE = re.compile(
    r"""
    (?:```[\s\S]*?```)       |  # code blocks
    (?:`[^`]+`)              |  # inline code
    (?:\#{1,6}\s+)           |  # headers
    (?:\*\*[^*]+\*\*)        |  # bold
    (?:\*[^*]+\*)            |  # italic
    (?:\[[^\]]+\]\([^)]+\))  |  # links
    (?:^[-*+]\s+)            |  # bullets
    (?:^\d+\.\s+)            |  # numbered lists
    (?:^>\s+)                |  # blockquotes
    (?:---+)                    # horizontal rules
    """,
    re.VERBOSE | re.MULTILINE,
)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class SpeechControls:
    audience_mode: str = "exec"    # exec | business | technical
    verbosity: int = 1             # 0..3
    tone: str = "neutral"          # cautious | neutral | confident
    locale: str = "en-US"


# ---------------------------------------------------------------------------
# Lexicon (acronym -> spoken expansion by audience)
# ---------------------------------------------------------------------------

LEXICON: Dict[str, Dict[str, str]] = {
    "NDR": {"exec": "net dollar retention", "business": "net dollar retention", "technical": "N D R"},
    "ARR": {"exec": "annual recurring revenue", "business": "annual recurring revenue", "technical": "A R R"},
    "MRR": {"exec": "monthly recurring revenue", "business": "monthly recurring revenue", "technical": "M R R"},
    "QoQ": {"exec": "quarter over quarter", "business": "quarter over quarter", "technical": "Q O Q"},
    "YoY": {"exec": "year over year", "business": "year over year", "technical": "Y O Y"},
    "MoM": {"exec": "month over month", "business": "month over month", "technical": "M O M"},
    "GMV": {"exec": "gross merchandise value", "business": "gross merchandise value", "technical": "G M V"},
    "AOV": {"exec": "average order value", "business": "average order value", "technical": "A O V"},
    "LTV": {"exec": "lifetime value", "business": "lifetime value", "technical": "L T V"},
    "CLV": {"exec": "customer lifetime value", "business": "customer lifetime value", "technical": "C L V"},
    "CAC": {"exec": "customer acquisition cost", "business": "customer acquisition cost", "technical": "C A C"},
    "ARPU": {"exec": "average revenue per user", "business": "average revenue per user", "technical": "A R P U"},
    "COGS": {"exec": "cost of goods sold", "business": "cost of goods sold", "technical": "C O G S"},
    "EBITDA": {"exec": "EBITDA", "business": "EBITDA", "technical": "EBITDA"},
    "KPI": {"exec": "key performance indicator", "business": "K P I", "technical": "K P I"},
    "SQL": {"exec": "S Q L", "business": "S Q L", "technical": "S Q L"},
    "ETL": {"exec": "E T L", "business": "E T L", "technical": "E T L"},
    "API": {"exec": "A P I", "business": "A P I", "technical": "A P I"},
    "ROI": {"exec": "return on investment", "business": "R O I", "technical": "R O I"},
    "ROAS": {"exec": "return on ad spend", "business": "return on ad spend", "technical": "R O A S"},
    "NPS": {"exec": "net promoter score", "business": "net promoter score", "technical": "N P S"},
    "CPC": {"exec": "cost per click", "business": "cost per click", "technical": "C P C"},
    "CPM": {"exec": "cost per thousand", "business": "cost per thousand", "technical": "C P M"},
    "CTR": {"exec": "click through rate", "business": "click through rate", "technical": "C T R"},
}


# ---------------------------------------------------------------------------
# Number helpers
# ---------------------------------------------------------------------------

def _to_float(num_str: str) -> Optional[float]:
    try:
        return float(num_str.replace(",", ""))
    except Exception:
        return None


def _sig_round(x: float, sig: int) -> float:
    if x == 0:
        return 0.0
    return round(x, sig - int(math.floor(math.log10(abs(x)))) - 1)


def _format_large(n: float, sig: int = 2) -> str:
    absn = abs(n)
    sign = "" if n >= 0 else "negative "
    if absn >= 1e12:
        return f"{sign}{_sig_round(absn / 1e12, sig)} trillion"
    if absn >= 1e9:
        return f"{sign}{_sig_round(absn / 1e9, sig)} billion"
    if absn >= 1e6:
        return f"{sign}{_sig_round(absn / 1e6, sig)} million"
    if absn >= 1e3:
        return f"{sign}{_sig_round(absn / 1e3, sig)} thousand"
    return str(_sig_round(n, sig))


# ---------------------------------------------------------------------------
# Core transforms
# ---------------------------------------------------------------------------

def strip_markdown(text: str) -> str:
    """Remove markdown formatting for speech."""
    text = CODE_BLOCK_RE.sub("", text)
    text = TABLE_RE.sub(" (see the data table on screen) ", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"#{1,6}\s+", "", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"^[-*+]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\d+\.\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^>\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"---+", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def expand_acronyms(text: str, mode: str) -> str:
    """Expand acronyms based on audience mode. First occurrence only."""
    seen = set()

    def repl(m):
        tok = m.group(0)
        if tok in seen:
            return tok
        seen.add(tok)
        if tok in LEXICON and mode in LEXICON[tok]:
            return LEXICON[tok][mode]
        return tok

    return ACRONYM_RE.sub(repl, text)


def normalize_numbers(text: str, controls: SpeechControls) -> str:
    """Normalize numbers for natural speech based on audience mode."""
    mode = controls.audience_mode

    def repl(m):
        prefix = m.group("prefix") or ""
        suffix = m.group("suffix") or ""
        raw = m.group("num")
        val = _to_float(raw)
        if val is None:
            return m.group(0)

        if suffix == "%":
            if mode == "exec":
                v = round(val, 1)
                return f"about {v} percent"
            elif mode == "business":
                v = round(val, 2 if abs(val) < 10 else 1)
                return f"{v} percent"
            else:
                v = round(val, 4) if abs(val) < 100 else round(val, 2)
                return f"{v} percent"

        if suffix in ("bps", "bp"):
            v = int(round(val))
            return f"{v} basis points"

        if prefix in ("$", "\u20ac", "\u00a3"):
            sym = {"$": "dollars", "\u20ac": "euros", "\u00a3": "pounds"}[prefix]
            if mode in ("exec", "business"):
                if abs(val) >= 1e3:
                    spoken = _format_large(val, sig=2)
                    return f"about {spoken} {sym}" if mode == "exec" else f"{spoken} {sym}"
                return f"{round(val, 2)} {sym}"
            return f"{val} {sym}"

        if abs(val) >= 1e6:
            if mode == "exec":
                return f"about {_format_large(val, sig=2)}"
            elif mode == "business":
                return _format_large(val, sig=2)
            return str(val)

        if isinstance(val, float) and "." in raw:
            return str(round(val, 2))
        if float(val).is_integer():
            return str(int(val))
        return str(val)

    return NUM_RE.sub(repl, text)


def convert_small_deltas_to_bps(text: str, controls: SpeechControls) -> str:
    """Convert small percentage deltas to basis points (exec/business only)."""
    if controls.audience_mode not in ("exec", "business"):
        return text

    def repl(m):
        sign = m.group(1)
        val = float(m.group(2))
        if abs(val) <= 2.0:
            bps = int(round(val * 100))
            direction = "up" if sign == "+" else "down"
            return f"{direction} {abs(bps)} basis points"
        return m.group(0)

    return re.sub(r"\b([+-])\s*(\d+(?:\.\d+)?)\s*percent\b", repl, text)


def chunk_text(text: str, max_chars: int = 500) -> List[str]:
    """Split text into chunks at sentence boundaries."""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks = []
    current = ""

    for sentence in sentences:
        if not sentence.strip():
            continue
        if len(current) + len(sentence) + 1 <= max_chars:
            current = (current + " " + sentence).strip()
        else:
            if current:
                chunks.append(current)
            if len(sentence) > max_chars:
                parts = re.split(r"(?<=[,;:])\s+", sentence)
                sub = ""
                for part in parts:
                    if len(sub) + len(part) + 1 <= max_chars:
                        sub = (sub + " " + part).strip()
                    else:
                        if sub:
                            chunks.append(sub)
                        sub = part.strip()
                current = sub
            else:
                current = sentence.strip()

    if current:
        chunks.append(current)

    return chunks if chunks else [text[:max_chars]]


# ---------------------------------------------------------------------------
# Main API
# ---------------------------------------------------------------------------

def normalize_for_speech(
    text: str,
    audience_mode: str = "exec",
    verbosity: int = 1,
    tone: str = "neutral",
    max_chars: int = 500,
) -> str:
    """
    Full normalization pipeline: markdown strip -> acronyms -> numbers -> chunking.

    Returns a single string ready for TTS, truncated to max_chars at a
    sentence boundary.
    """
    controls = SpeechControls(
        audience_mode=audience_mode,
        verbosity=verbosity,
        tone=tone,
    )

    text = strip_markdown(text)
    text = expand_acronyms(text, controls.audience_mode)
    text = normalize_numbers(text, controls)
    text = convert_small_deltas_to_bps(text, controls)

    text = re.sub(r"\s+", " ", text).strip()

    if verbosity == 0:
        sentences = re.split(r"(?<=[.!?])\s+", text)
        text = " ".join(sentences[:2])
    elif verbosity == 1:
        sentences = re.split(r"(?<=[.!?])\s+", text)
        text = " ".join(sentences[:5])
    elif verbosity == 2:
        sentences = re.split(r"(?<=[.!?])\s+", text)
        text = " ".join(sentences[:8])

    if len(text) > max_chars:
        chunks = chunk_text(text, max_chars)
        text = chunks[0]

    return text
