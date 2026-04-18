import threading

import re
import language_tool_python

from app.services.paragraph_rules import find_paragraph_grammar_hints, merge_without_overwriting_lt

_tools: dict[str, language_tool_python.LanguageTool] = {}
_tools_lock = threading.Lock()


def _normalize_language(language: str | None) -> str:
    # LanguageTool expects e.g. "en-US" or "en-GB". Keep defaults stable.
    if not language:
        return "en-US"
    return str(language).strip() or "en-US"


def _get_tool(language: str | None) -> language_tool_python.LanguageTool:
    lang = _normalize_language(language)
    with _tools_lock:
        tool = _tools.get(lang)
        if tool is None:
            tool = language_tool_python.LanguageTool(lang)
            # Stricter style/clarity rules where LanguageTool exposes them (free rules still
            # miss many real errors, e.g. collective noun + verb agreement).
            tool.picky = True
            _tools[lang] = tool
        return tool


_AMERICAN_TO_BRITISH_SUFFIXES: tuple[tuple[str, str], ...] = (
    ("izations", "isations"),
    ("ization", "isation"),
    ("izing", "ising"),
    ("ized", "ised"),
)


def _variant_spelling_hints(text: str, language: str) -> list[dict]:
    """
    LanguageTool's free rules don't always flag US/UK variant spellings.
    Add lightweight variant hints for en-GB (e.g. globalization -> globalisation).
    """
    if language != "en-GB":
        return []

    # Only target common -ize/-ization variants; avoid broad -ize -> -ise which
    # would create many false positives (size, prize, etc.).
    pattern = re.compile(r"\b[A-Za-z]{5,}(?:izations|ization|izing|ized)\b")
    out: list[dict] = []

    for m in pattern.finditer(text):
        bad = m.group(0)
        lower = bad.lower()
        better: str | None = None
        for src, dst in _AMERICAN_TO_BRITISH_SUFFIXES:
            if lower.endswith(src):
                better = bad[:-len(src)] + dst
                break
        if not better or better == bad:
            continue

        out.append(
            {
                "type": "spelling",
                "bad": bad,
                "better": [better],
                "offset": m.start(),
                "length": len(bad),
                "description": {
                    "en": "Possible spelling mistake. This looks like an American English variant; consider the British English spelling."
                },
            }
        )

    return out


def check_text(
    text: str,
    include_types: frozenset[str] | None = None,
    language: str | None = None,
):
    if include_types is None:
        include_types = frozenset({"spelling", "grammar"})

    normalized_language = _normalize_language(language)
    tool = _get_tool(normalized_language)

    # Dictionary spelling (TYPOS) often hides or crowds out grammar rules. For
    # grammar-only requests, turn off spellchecking for this check so agreement
    # and grammar rules can surface (shared tool is configured under a lock).
    grammar_only = include_types == frozenset({"grammar"})

    # LanguageTool's python wrapper shares state on the tool instance (e.g.
    # disabled categories). Guard each tool instance for thread safety.
    tool_lock = getattr(tool, "_cursor_lock", None)
    if tool_lock is None:
        tool_lock = threading.Lock()
        setattr(tool, "_cursor_lock", tool_lock)

    with tool_lock:
        if grammar_only:
            prev_disabled = set(tool.disabled_categories)
            tool.disable_spellchecking()
            try:
                matches = tool.check(text)
            finally:
                tool.disabled_categories = prev_disabled
        else:
            matches = tool.check(text)

    results = []

    for match in matches:
        category_id = getattr(getattr(match.rule, "category", None), "id", None)
        error_type = "spelling" if (
            match.rule_issue_type in ("misspelling", "typographical")
            or category_id == "TYPOS"
        ) else "grammar"

        if error_type not in include_types:
            continue

        results.append({
            "type": error_type,
            "bad": text[match.offset: match.offset + match.error_length],
            "better": match.replacements[:3],
            "offset": match.offset,
            "length": match.error_length,
            "description": {
                "en": match.message
            }
        })

    if "spelling" in include_types:
        variant_hints = _variant_spelling_hints(text, normalized_language)
        results = merge_without_overwriting_lt(results, variant_hints)

    if "grammar" in include_types:
        hints = find_paragraph_grammar_hints(text)
        results = merge_without_overwriting_lt(results, hints)

    return results