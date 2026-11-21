"""Machine-owned score prefixes used as a view over semantic titles."""
from __future__ import annotations

import re

SCORE_LEVELS = ('S1', 'S2', 'S3', 'S4')
SCORE_STATUSES = ('scored', 'insufficient_data', 'disabled')
_SCORE_TOKEN = r'(?:S[1-4]·\d{1,3}分|S1·\d{1,3}分（窗口未知）|未评分)'
SCORE_PREFIX_PATTERN = re.compile(rf'^(?P<token>{_SCORE_TOKEN})｜')
_WORKTREE_PREFIX_PATTERN = re.compile(r'^(?:(?:\[工作树\]|\[worktree\])\s*)+')


def _raise(message):
    # Imported lazily to avoid the title_runtime -> title_score import cycle.
    from title_runtime import TitleError
    raise TitleError(message)


def render_score_prefix(level, score_status, score, *, baseline_score=None):
    if score_status not in SCORE_STATUSES:
        _raise('评分状态无效')
    if baseline_score is not None:
        if (level != 'S2' or score_status != 'insufficient_data' or score is not None
                or type(baseline_score) is not int or not 0 <= baseline_score <= 100):
            _raise('仅可在 S2 缺少窗口时附上有效的 S1 基础分')
        return f'S1·{baseline_score}分（窗口未知）'
    if score_status == 'disabled':
        return None
    if score_status == 'insufficient_data':
        if score is not None:
            _raise('待评估状态不能带分数')
        return '未评分'
    if level not in SCORE_LEVELS or type(score) is not int or not 0 <= score <= 100:
        _raise('已评分状态须提供 S1 到 S4 及 0 到 100 的整数分数')
    return f'{level}·{score}分'


def parse_score_prefix(value):
    if not isinstance(value, str):
        return None
    value = _WORKTREE_PREFIX_PATTERN.sub('', value.strip())
    match = SCORE_PREFIX_PATTERN.match(value)
    return match.group('token') if match else None


def split_score_prefix(value):
    """Return (score token or None, title without the machine prefix)."""
    if not isinstance(value, str):
        return None, value
    stripped = value.strip()
    worktree = _WORKTREE_PREFIX_PATTERN.match(stripped)
    worktree_prefix = worktree.group(0) if worktree else ''
    remainder = stripped[len(worktree_prefix):]
    match = SCORE_PREFIX_PATTERN.match(remainder)
    if not match:
        return None, stripped
    return match.group('token'), worktree_prefix + remainder[match.end():].strip()


def apply_score_prefix(value, prefix):
    if not isinstance(value, str):
        _raise('标题必须是字符串')
    if prefix is not None and not re.fullmatch(_SCORE_TOKEN, prefix):
        _raise('评分前缀无效')
    current, core = split_score_prefix(value)
    del current
    worktree = _WORKTREE_PREFIX_PATTERN.match(core)
    worktree_prefix = worktree.group(0) if worktree else ''
    semantic = core[len(worktree_prefix):]
    if prefix is None:
        return worktree_prefix + semantic
    return f'{worktree_prefix}{prefix}｜{semantic}'
