import threading

import language_tool_python

from app.services.paragraph_rules import find_paragraph_grammar_hints, merge_without_overwriting_lt

tool = language_tool_python.LanguageTool("en-US")
# Stricter style/clarity rules where LanguageTool exposes them (free rules still
# miss many real errors, e.g. collective noun + verb agreement).
tool.picky = True
_tool_lock = threading.Lock()


def check_text(text: str, include_types: frozenset[str] | None = None):
    if include_types is None:
        include_types = frozenset({"spelling", "grammar"})

    # Dictionary spelling (TYPOS) often hides or crowds out grammar rules. For
    # grammar-only requests, turn off spellchecking for this check so agreement
    # and grammar rules can surface (shared tool is configured under a lock).
    grammar_only = include_types == frozenset({"grammar"})

    with _tool_lock:
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
        error_type = "grammar"

        if match.rule_issue_type in ("misspelling", "typographical"):
            error_type = "spelling"

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

    if "grammar" in include_types:
        hints = find_paragraph_grammar_hints(text)
        results = merge_without_overwriting_lt(results, hints)

    return results