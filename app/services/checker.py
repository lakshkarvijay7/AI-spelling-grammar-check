import threading

from copy import deepcopy
from functools import lru_cache
import os
import re
import zlib
import language_tool_python

from app.services.paragraph_rules import find_paragraph_grammar_hints, merge_without_overwriting_lt

_tools: dict[str, language_tool_python.LanguageTool] = {}
_tools_lock = threading.Lock()
LT_PICKY = os.getenv("LT_PICKY", "0").strip().lower() in {"1", "true", "yes", "on"}
CHECK_CACHE_TEXT_MAX = int(os.getenv("CHECK_CACHE_TEXT_MAX", "5000"))


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
            # `picky` is slower; keep it configurable for latency-sensitive APIs.
            tool.picky = LT_PICKY
            _tools[lang] = tool
        return tool


def warm_tools(languages: tuple[str, ...] = ("en-US", "en-GB")) -> None:
    """Initialize LanguageTool instances at startup to avoid first-request latency."""
    for lang in languages:
        _get_tool(lang)


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


def _check_text_impl(
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

    def _make_error_id(item: dict) -> str:
        raw = "|".join(
            [
                str(item.get("type", "")),
                str(item.get("offset", "")),
                str(item.get("length", "")),
                str(item.get("bad", "")),
                str(item.get("description", {}).get("en", "")),
            ]
        )
        return f"e{zlib.crc32(raw.encode('utf-8')) & 0xFFFFFFFF}"

    for match in matches:
        # `language_tool_python` changed Match shape across versions:
        # newer versions expose `category`/`rule_issue_type` directly and remove `rule`.
        category_id = getattr(match, "category", None)
        if category_id is None:
            category_id = getattr(getattr(match, "rule", None), "category", None)
            category_id = getattr(category_id, "id", category_id)

        issue_type = getattr(match, "rule_issue_type", None)
        if issue_type is None:
            issue_type = getattr(match, "ruleIssueType", None)

        # Keep spelling detection strict to avoid mislabeling contextual grammar
        # suggestions (e.g. "other" -> "others") as spelling.
        is_spelling = (
            category_id == "TYPOS"
            or (category_id is None and issue_type in ("misspelling", "typographical"))
        )
        error_type = "spelling" if is_spelling else "grammar"

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

    for item in results:
        item["id"] = _make_error_id(item)

    return results


@lru_cache(maxsize=256)
def _check_text_cached(
    text: str,
    include_types: frozenset[str],
    language: str,
) -> tuple[dict, ...]:
    # Store immutable container in cache; callers receive a deep copy.
    return tuple(_check_text_impl(text, include_types, language))


def check_text(
    text: str,
    include_types: frozenset[str] | None = None,
    language: str | None = None,
):
    if include_types is None:
        include_types = frozenset({"spelling", "grammar"})

    normalized_language = _normalize_language(language)

    # Cache repeated checks (same text + types + language). Skip for very large
    # texts to prevent excessive memory growth.
    if len(text) <= CHECK_CACHE_TEXT_MAX:
        return deepcopy(list(_check_text_cached(text, include_types, normalized_language)))

    return _check_text_impl(text, include_types, normalized_language)
