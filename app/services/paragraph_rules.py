"""
High-precision grammar hints for full paragraphs.

LanguageTool often misses agreement and some style/wording issues; these patterns
complement LT. Spans follow common checker UX: highlight the smallest offending
token when possible (e.g. “have” not the whole noun phrase).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class _Rule:
    pattern: re.Pattern[str]
    message: str
    replacements: list[str] | Callable[[re.Match[str]], list[str]]
    # 0 = entire regex match; else use that capture group’s span for bad/offset/length
    highlight_group: int = 0


def _swap_is_in_globalized(m: re.Match[str]) -> list[str]:
    return [re.sub(r"(?i)\bis\s+a\s+globalized\b", "in a globalized", m.group(0), count=1)]


_RULES: tuple[_Rule, ...] = (
    _Rule(
        re.compile(r"(?i)\b(this|it)\s+(are)\b"),
        "Agreement error.",
        lambda m: ["is"],
        highlight_group=2,
    ),
    _Rule(
        re.compile(r"(?i)\b(?:\w+\s+)?education\s+(have)\b"),
        "Agreement error.",
        lambda m: ["has"],
        highlight_group=1,
    ),
    _Rule(
        re.compile(
            r"(?i)\b(information|knowledge|furniture|equipment|traffic|weather|"
            r"advice|evidence|machinery|luggage|homework|research)\s+(have)\b"
        ),
        "Agreement error.",
        lambda m: ["has"],
        highlight_group=2,
    ),
    _Rule(
        re.compile(r"(?i)\b(success|progress|opportunity)\s+is\s+a\s+globalized\b"),
        "Possible wrong word: you may mean “in a globalized …” rather than “is a globalized …”.",
        _swap_is_in_globalized,
        highlight_group=0,
    ),
    _Rule(
        re.compile(r"(?i)\bis\s+(sufficient)\b"),
        "Use enough.",
        lambda m: ["enough"],
        highlight_group=1,
    ),
)


def _overlaps(a0: int, a1: int, b0: int, b1: int) -> bool:
    return not (a1 <= b0 or b1 <= a0)


def find_paragraph_grammar_hints(text: str) -> list[dict]:
    hits: list[dict] = []
    for rule in _RULES:
        for m in rule.pattern.finditer(text):
            g = rule.highlight_group
            if g > 0:
                start, end = m.span(g)
            else:
                start, end = m.span(0)
            if callable(rule.replacements):
                better = rule.replacements(m)[:3]
            else:
                better = rule.replacements[:3]
            hits.append(
                {
                    "type": "grammar",
                    "bad": text[start:end],
                    "better": better,
                    "offset": start,
                    "length": end - start,
                    "description": {"en": rule.message},
                }
            )

    hits.sort(key=lambda h: (h["offset"], -h["length"]))

    merged: list[dict] = []
    for h in hits:
        h0, h1 = h["offset"], h["offset"] + h["length"]
        if any(_overlaps(h0, h1, e["offset"], e["offset"] + e["length"]) for e in merged):
            continue
        merged.append(h)

    merged.sort(key=lambda h: h["offset"])
    return merged


def merge_without_overwriting_lt(
    lt_errors: list[dict], hints: list[dict]
) -> list[dict]:
    """Append hints that do not overlap spans already covered by LanguageTool."""
    lt_blocks = [(e["offset"], e["offset"] + e["length"]) for e in lt_errors]
    extra: list[dict] = []
    for h in hints:
        h0, h1 = h["offset"], h["offset"] + h["length"]
        if any(_overlaps(h0, h1, t0, t1) for t0, t1 in lt_blocks):
            continue
        extra.append(h)
    out = list(lt_errors) + extra
    out.sort(key=lambda e: e["offset"])
    return out
