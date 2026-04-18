"""
Enhanced grammar + spelling rule engine
Designed to complement LanguageTool for paragraph-level corrections
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, List, Dict


# =========================
# Rule Model
# =========================
@dataclass(frozen=True)
class _Rule:
    pattern: re.Pattern[str]
    message: str
    replacements: List[str] | Callable[[re.Match[str]], List[str]]
    highlight_group: int = 0
    category: str = "grammar"  # NEW: grammar / spelling / style


# =========================
# Helpers
# =========================
def _overlaps(a0: int, a1: int, b0: int, b1: int) -> bool:
    return not (a1 <= b0 or b1 <= a0)


def _swap_is_in_globalized(m: re.Match[str]) -> List[str]:
    return [re.sub(r"(?i)\bis\s+a\s+globalized\b", "in a globalized", m.group(0), count=1)]


# =========================
# Core Rules
# =========================
_RULES: List[_Rule] = [

    # -------------------------
    # Agreement Rules
    # -------------------------
    _Rule(
        re.compile(r"(?i)\b(this|it)\s+(are)\b"),
        "Agreement error.",
        lambda m: ["is"],
        highlight_group=2,
    ),
    _Rule(
        re.compile(r"(?i)\b(?:\w+\s+)?education\s+(are|have)\b"),
        "Agreement error.",
        lambda m: ["is" if m.group(1).lower() == "are" else "has"],
        highlight_group=1,
    ),
    _Rule(
        re.compile(r"(?i)\b(information|knowledge|equipment|advice|evidence)\s+(have)\b"),
        "Agreement error.",
        lambda m: ["has"],
        highlight_group=2,
    ),

    # -------------------------
    # Others vs Other
    # -------------------------
    _Rule(
        re.compile(r"(?i)\bother\s+(argue|believe|say|think)\b"),
        "Use plural noun 'others'.",
        lambda m: [f"others {m.group(1)}"],
        highlight_group=0,
    ),

    # -------------------------
    # Verb Form Errors
    # -------------------------
    _Rule(
        re.compile(r"(?i)\b(is|are|was|were)\s+(discuss|explain|describe|analyze)\b"),
        "Incorrect verb form after auxiliary.",
        lambda m: [m.group(2) + "ed"],
        highlight_group=2,
    ),

    _Rule(
        re.compile(r"(?i)\b(he|she|it|this|that)\s+(argue|believe|say|think)\b"),
        "Third-person singular verbs need -s.",
        lambda m: [m.group(2) + "s"],
        highlight_group=2,
    ),

    # -------------------------
    # Article Rules
    # -------------------------
    _Rule(
        re.compile(r"(?i)\ba\s+([aeiou]\w*)\b"),
        "Use 'an' before vowel sounds.",
        lambda m: [f"an {m.group(1)}"],
        highlight_group=0,
    ),

    # -------------------------
    # Style Improvements
    # -------------------------
    _Rule(
        re.compile(r"(?i)\bis\s+(sufficient)\b"),
        "Use 'enough' instead of 'sufficient' for simplicity.",
        lambda m: ["enough"],
        highlight_group=1,
        category="style",
    ),

    _Rule(
        re.compile(r"(?i)\bdue to\s+(globalization|technology)\b"),
        "Consider 'because of' for clarity.",
        lambda m: [f"because of {m.group(1)}"],
        highlight_group=0,
        category="style",
    ),

    _Rule(
        re.compile(r"(?i)\b(success|progress|opportunity)\s+is\s+a\s+globalized\b"),
        "Possible wrong phrasing.",
        _swap_is_in_globalized,
        highlight_group=0,
        category="style",
    ),
]


# =========================
# Spelling Rules
# =========================
COMMON_SPELLING = {
    "teh": "the",
    "recieve": "receive",
    "becuase": "because",
    "definately": "definitely",
    "enviroment": "environment",
    "goverment": "government",
    "arguement": "argument",
}

for wrong, correct in COMMON_SPELLING.items():
    _RULES.append(
        _Rule(
            re.compile(rf"(?i)\b{wrong}\b"),
            "Spelling mistake.",
            lambda m, c=correct: [c],
            highlight_group=0,
            category="spelling",
        )
    )


# =========================
# UK/US Normalization
# =========================
GB_VARIANTS = {
    "color": "colour",
    "favor": "favour",
    "organize": "organise",
    "analyze": "analyse",
}

for us, uk in GB_VARIANTS.items():
    _RULES.append(
        _Rule(
            re.compile(rf"(?i)\b{us}\b"),
            "Use British English spelling.",
            lambda m, c=uk: [c],
            highlight_group=0,
            category="spelling",
        )
    )


# =========================
# Main Engine
# =========================
def find_paragraph_grammar_hints(text: str) -> List[Dict]:
    hits: List[Dict] = []

    for rule in _RULES:
        for m in rule.pattern.finditer(text):

            # Select highlight span
            if rule.highlight_group > 0:
                start, end = m.span(rule.highlight_group)
            else:
                start, end = m.span(0)

            # Generate suggestions
            if callable(rule.replacements):
                better = rule.replacements(m)[:3]
            else:
                better = rule.replacements[:3]

            hits.append(
                {
                    "type": rule.category,
                    "bad": text[start:end],
                    "better": better,
                    "offset": start,
                    "length": end - start,
                    "description": {"en": rule.message},
                }
            )

    # Sort by offset
    hits.sort(key=lambda h: (h["offset"], -h["length"]))

    # Remove overlaps
    merged: List[Dict] = []
    for h in hits:
        h0, h1 = h["offset"], h["offset"] + h["length"]
        if any(_overlaps(h0, h1, e["offset"], e["offset"] + e["length"]) for e in merged):
            continue
        merged.append(h)

    merged.sort(key=lambda h: h["offset"])
    return merged


# =========================
# Merge with LanguageTool
# =========================
def merge_without_overwriting_lt(
    lt_errors: List[Dict], hints: List[Dict]
) -> List[Dict]:

    lt_blocks = [(e["offset"], e["offset"] + e["length"]) for e in lt_errors]

    extra: List[Dict] = []
    for h in hints:
        h0, h1 = h["offset"], h["offset"] + h["length"]

        if any(_overlaps(h0, h1, t0, t1) for t0, t1 in lt_blocks):
            continue

        extra.append(h)

    out = list(lt_errors) + extra
    out.sort(key=lambda e: e["offset"])
    return out