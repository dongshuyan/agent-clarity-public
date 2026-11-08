"""MIT-licensed helpers copied from panda-z519/agent-session-titles.
Upstream commit: 2d931a54a736a57c23a3e9a7fcfca56031dfd5f3.
See ../LICENSES/agent-session-titles.txt. No upstream runtime dependency.
"""
from typing import Any
import re

from title_score import split_score_prefix
TITLE_SEGMENTS = ("status", "initial_request", "progress")
TITLE_SEPARATORS = {"zh": "｜", "en": " | "}
WORKTREE_PREFIX_PATTERN = re.compile(r"^(?:(?:\[工作树\]|\[worktree\])\s*)+")

def parse_three_part_title(value: Any) -> tuple[str, str, tuple[str, str, str]] | None:
    if not isinstance(value, str):
        return None
    score_prefix, without_score = split_score_prefix(value)
    prefix_match = WORKTREE_PREFIX_PATTERN.match(without_score.strip())
    prefix = prefix_match.group(0) if prefix_match else ""
    if score_prefix:
        prefix += score_prefix + "｜"
    title = WORKTREE_PREFIX_PATTERN.sub("", without_score).strip()
    matches: list[tuple[str, str, tuple[str, str, str]]] = []
    for language, separator in TITLE_SEPARATORS.items():
        parts = tuple(part.strip() for part in title.split(separator))
        if len(parts) == 3 and all(parts):
            matches.append((language, prefix, parts))
    return matches[0] if len(matches) == 1 else None

def protected_segments(state: dict[str, Any]) -> set[str]:
    values = state.get("locked_segments", [])
    if not isinstance(values, list):
        return set()
    return {value for value in values if value in TITLE_SEGMENTS}

def merge_protected_title(
    state: dict[str, Any],
    current: str,
    requested: str,
) -> str:
    if not state.get("segment_protection_active"):
        return requested
    current_title = parse_three_part_title(current)
    requested_title = parse_three_part_title(requested)
    if current_title is None or requested_title is None:
        return ""
    locked = protected_segments(state)
    parts = list(requested_title[2])
    for index, segment in enumerate(TITLE_SEGMENTS):
        if segment in locked:
            parts[index] = current_title[2][index]
    # A score prefix is a machine-owned decoration. A regular semantic title
    # update has no score prefix, so keep the currently visible one. This lets
    # manual score-prefix edits remain visible while the semantic segments keep
    # their existing protection behavior.
    decoration = requested_title[1] or current_title[1]
    return f"{decoration}{TITLE_SEPARATORS[requested_title[0]].join(parts)}"
