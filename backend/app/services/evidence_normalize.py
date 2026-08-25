"""证据引用规范化：把模型生成的引用在原文中匹配为精确子串。"""

import re
from difflib import SequenceMatcher

# 仅保留字母/数字/CJK（与前端归一化一致，符号全部忽略）
_NON_ALNUM = re.compile(r"[\W_]", re.UNICODE)
_QUOTE_SEGMENT_SPLIT = re.compile(r"…|\.{2,}")

MATCH_THRESHOLD = 0.75


def normalize_evidence_text(text: str) -> str:
    """归一化：仅保留字母/数字/CJK，英文转小写。"""
    return _NON_ALNUM.sub("", text).lower()


def build_index_map(text: str) -> list[int]:
    """归一化字符位置 → 原文索引映射（跳过原文中的符号）。"""
    mapping: list[int] = []
    position = 0
    for i, char in enumerate(text):
        if _NON_ALNUM.match(char):
            continue
        mapping.append(i)
        position += 1
    return mapping


def _locate_prefix(normalized_text: str, normalized_quote: str) -> int:
    """用引用前 6~12 个连续字符定位候选起点，找不到返回 -1。"""
    prefix_len = min(len(normalized_quote), 12)
    while prefix_len >= 6:
        index = normalized_text.find(normalized_quote[:prefix_len])
        if index >= 0:
            return index
        prefix_len -= 1
    return -1


def normalize_evidence_quote(text: str, quote: str) -> str | None:
    """在原文中模糊定位引用，返回原文精确子串；相似度不足返回 None。"""
    normalized_text = normalize_evidence_text(text)
    normalized_quote = normalize_evidence_text(quote)
    if not normalized_text or not normalized_quote:
        return None
    index_map = build_index_map(text)

    start = _locate_prefix(normalized_text, normalized_quote)
    if start < 0:
        return None

    # 在候选起点附近滑动窗口，取与引用相似度最高的窗口
    quote_len = len(normalized_quote)
    window_min = max(1, int(quote_len * 0.85))
    window_max = quote_len + max(5, int(quote_len * 0.15))
    best_ratio = 0.0
    best_start = -1
    best_size = 0
    search_start = max(0, start - window_max)
    search_end = min(len(normalized_text), start + window_max + quote_len)
    for size in range(window_min, window_max + 1):
        for window_start in range(search_start, search_end - size + 1):
            chunk = normalized_text[window_start : window_start + size]
            ratio = SequenceMatcher(None, chunk, normalized_quote).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_start = window_start
                best_size = size

    if best_ratio < MATCH_THRESHOLD or best_start < 0:
        return None

    orig_start = index_map[best_start] if best_start < len(index_map) else None
    orig_end = (
        index_map[best_start + best_size - 1]
        if best_start + best_size - 1 < len(index_map)
        else None
    )
    if orig_start is None or orig_end is None:
        return None
    return text[orig_start : orig_end + 1]


def split_evidence_quote_segments(quote: str) -> list[str]:
    """按省略号把引用拆段，返回非空段。"""
    return [segment.strip() for segment in _QUOTE_SEGMENT_SPLIT.split(quote) if segment.strip()]
