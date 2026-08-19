"""确定性文本相似度工具：供关系判断与语义检索共用。"""

import re

_PUNCT_RE = re.compile(r"[\s\W_]+", re.UNICODE)


def normalize(value: str) -> str:
    """归一化文本：去空白/标点并转小写。"""
    return _PUNCT_RE.sub("", value).casefold()


def bigrams(value: str) -> set[str]:
    """提取字符 bigram 集合。"""
    normalized = normalize(value)
    return {normalized[i : i + 2] for i in range(max(0, len(normalized) - 1))}


def overlap(left: set[str], right: set[str]) -> float:
    """计算两个集合的 Jaccard 重叠。"""
    if not left and not right:
        return 0.0
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def text_pair_similarity(
    left_title: str,
    left_content: str,
    right_title: str,
    right_content: str,
) -> float:
    """计算两段带标题与内容文本的确定性相似度分数。"""
    left_title_n = normalize(left_title)
    right_title_n = normalize(right_title)
    score = 0.0
    if left_title_n and left_title_n == right_title_n:
        score += 100
    elif left_title_n and right_title_n and (
        left_title_n in right_title_n or right_title_n in left_title_n
    ):
        score += 40
    score += overlap(bigrams(left_title), bigrams(right_title)) * 30
    score += overlap(bigrams(left_content), bigrams(right_content)) * 20
    return score
