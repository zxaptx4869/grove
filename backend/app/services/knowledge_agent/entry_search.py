"""有界正式 Entry 查找服务：受控召回 → 去重排序 → 快照装配 → 原子提交。
只读执行图约束：
- 范围只来自 Run 固化的 owner / Workspace / 可选项目；模型或客户端不能指定
  Workspace、Project、Node、Entry id 或目录节点级范围；
- 只保留正式 Entry，排除 Candidate/Draft/Extraction/已删除与范围外对象；
- 结果项是对象快照，不生成综合回答、Citation 或 Run Evidence；
- 搜索命中不推进事实工作集、不创建输出上下文版本；
- 候选/结果/摘要/JSON 字节上限全部由服务端 settings 控制。
"""

import base64
import hashlib
import hmac
import json
import logging

from fastapi import HTTPException, status
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import Entry
from app.models.knowledge_agent import (
    RESULT_COMPLETENESS_COMPLETE,
    RESULT_COMPLETENESS_LIMITED,
    RESULT_COMPLETENESS_UNKNOWN,
    RESULT_MODE_ENTRIES,
    SCOPE_PROJECT,
)
from app.schemas.knowledge_agent import (
    KnowledgeEntryResultItemOut,
    KnowledgeEntryResultSnapshotOut,
    KnowledgeEntryResultsPageOut,
)
from app.services.entry import entry_baseline, entry_fingerprint
from app.services.knowledge_agent.evidence import build_node_path_map

logger = logging.getLogger(__name__)

ENTRY_SEARCH_PROMPT_VERSION = "v1"
RESULT_CURSOR_VERSION = 1
_CURSOR_SECRET_FALLBACK = "grove-entry-result-cursor-v1"

# 中文查询常见框架词（按长度优先）：不携带检索意图，只用于匹配线索与摘要窗口，
# 不影响主召回与持久化查询文本。
_QUERY_FRAME_PREFIXES = (
    "请帮我",
    "麻烦帮我",
    "帮我",
    "请问",
    "麻烦",
    "帮忙",
    "有哪些",
    "有什么",
    "找一下",
    "查找一下",
    "搜索一下",
    "查询一下",
    "看看",
    "找出",
    "查找",
    "搜索",
    "列出",
    "整理",
    "查询",
    "了解",
    "关于",
    "有关",
    "什么",
    "一下",
)
_QUERY_FRAME_SUFFIXES = (
    "相关的知识点",
    "相关知识要点",
    "相关知识点",
    "相关的知识",
    "相关知识条目",
    "相关知识",
    "相关条目",
    "知识要点",
    "知识点",
    "知识条目",
    "知识内容",
    "知识信息",
    "知识资料",
    "知识库",
    "知识",
    "有哪些",
    "有什么",
    "是什么",
    "是哪些",
    "哪些",
    "什么",
)


def _strip_query_frames(query: str) -> str:
    """剥离中文查询框架词，保留核心检索意图（仅用于匹配线索与摘要窗口）。"""
    text = query.strip()
    changed = True
    while changed and text:
        changed = False
        for token in _QUERY_FRAME_PREFIXES:
            if text.startswith(token):
                text = text[len(token) :].strip()
                changed = True
                break
        for token in _QUERY_FRAME_SUFFIXES:
            if text.endswith(token) and len(text) > len(token):
                text = text[: -len(token)].strip()
                changed = True
                break
        if text.startswith(("的", "和", "与")):
            text = text[1:].strip()
            changed = True
        if text.endswith("的") and len(text) > 1:
            text = text[:-1].strip()
            changed = True
    if len(text) < 2 or text in {"相关", "的", "和", "与"}:
        # 框架词剥离失败或只剩框架残留：回退原始查询，避免匹配语义漂移
        return query.strip()
    return text


def _cursor_secret() -> str:
    """返回游标签名密钥：优先应用密钥，未配置时使用稳定兜底。"""
    return get_settings().auth_secret_key or _CURSOR_SECRET_FALLBACK


def _encode_result_cursor(
    *,
    run_id: int,
    workspace_id: int,
    owner_user_id: int,
    schema_version: str,
    offset: int,
) -> str:
    """生成绑定 Run/范围/schema/偏移的不透明分页游标（带签名）。"""
    payload = {
        "v": RESULT_CURSOR_VERSION,
        "run": run_id,
        "ws": workspace_id,
        "owner": owner_user_id,
        "schema": schema_version,
        "offset": offset,
    }
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    signature = hmac.new(
        _cursor_secret().encode("utf-8"),
        raw.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:24]
    encoded = base64.urlsafe_b64encode(f"{signature}.{raw}".encode()).decode(
        "ascii"
    )
    return encoded


def _decode_result_cursor(raw: str) -> dict | None:
    """解析并校验游标；签名不匹配或结构非法返回 None。"""
    try:
        decoded = base64.urlsafe_b64decode(raw.encode("ascii")).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None
    signature, sep, payload = decoded.partition(".")
    if not sep:
        return None
    expected = hmac.new(
        _cursor_secret().encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:24]
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        data = json.loads(payload)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    if (
        data.get("v") != RESULT_CURSOR_VERSION
        or not isinstance(data.get("offset"), int)
        or data["offset"] < 0
    ):
        return None
    return data


async def paginate_entry_results(
    db: AsyncSession,
    run,
    *,
    cursor: str | None,
    limit: int | None,
    default_page_size: int,
    max_page_size: int,
) -> KnowledgeEntryResultsPageOut:
    """从同一持久化快照读取结果页；不重新搜索、不改写历史。

    游标绑定 Run / owner / Workspace / schema / 偏移并带签名；篡改、
    跨 Run/用户/Workspace 使用与越界返回稳定 400；非 entries Run 或
    无快照返回 404。
    """
    if run.actual_result_mode != RESULT_MODE_ENTRIES or not run.entry_result_json:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="该 Run 没有结构化结果",
        )
    try:
        snapshot = KnowledgeEntryResultSnapshotOut.model_validate_json(
            run.entry_result_json
        )
    except ValidationError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="结果快照不可用",
        ) from None

    offset = 0
    if cursor:
        data = _decode_result_cursor(cursor)
        if data is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="无效的结果游标",
            )
        if (
            data.get("run") != run.id
            or data.get("ws") != run.workspace_id
            or data.get("owner") != run.owner_user_id
            or data.get("schema") != snapshot.schema_version
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="游标与结果 Run 不匹配",
            )
        offset = int(data["offset"])

    total = len(snapshot.items)
    if offset > total:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="结果游标越界",
        )
    page_size = (
        default_page_size
        if limit is None
        else max(1, min(int(limit), max_page_size))
    )
    items = snapshot.items[offset : offset + page_size]
    next_offset = offset + len(items)
    has_more = next_offset < total
    next_cursor = None
    if has_more:
        next_cursor = _encode_result_cursor(
            run_id=run.id,
            workspace_id=run.workspace_id,
            owner_user_id=run.owner_user_id,
            schema_version=snapshot.schema_version,
            offset=next_offset,
        )
    return KnowledgeEntryResultsPageOut(
        schema_version=snapshot.schema_version,
        status=snapshot.status,
        completeness=snapshot.completeness,
        items=items,
        returned_count=len(items),
        total_in_snapshot=total,
        candidate_limit=snapshot.candidate_limit,
        has_more=has_more,
        next_cursor=next_cursor,
        warning=snapshot.warning,
        snapshot_updated_at=snapshot.snapshot_updated_at,
        set_summary=snapshot.set_summary,
        sort=snapshot.sort,
        count=snapshot.count,
        group_counts=snapshot.group_counts,
        output_completeness=snapshot.output_completeness,
        warnings=snapshot.warnings,
    )


def _bound(text: str, limit: int) -> str:
    """按字符数确定性截断，超长时补省略号。"""
    text = " ".join(str(text).split())
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


def _content_excerpt(content: str, query: str, excerpt_chars: int) -> str:
    """生成有界正文摘要：优先围绕首个可验证命中位置，否则取正文前缀。"""
    text = (content or "").strip()
    if not text:
        return ""
    q = _strip_query_frames(query).casefold()
    if not q:
        return _bound(text, excerpt_chars)
    position = text.casefold().find(q)
    if position < 0:
        return _bound(text, excerpt_chars)
    half = max(0, (excerpt_chars - len(q)) // 2)
    start = max(0, position - half)
    end = min(len(text), position + len(q) + half)
    snippet = text[start:end]
    return _bound(snippet, excerpt_chars)


def _longest_common_substring(left: str, right: str) -> str:
    """返回两个字符串的最长公共子串（大小写不敏感，限制长度避免大输入）。"""
    a = left.casefold()
    b = right.casefold()
    if not a or not b:
        return ""
    # 只取查询侧的有意义片段，避免长正文上的 O(n*m) 退化
    if len(a) > 200:
        a = a[:200]
    best = ""
    for start in range(len(a)):
        for end in range(start + 2, len(a) + 1):
            if end - start > 120:
                break
            segment = a[start:end]
            if segment in b and len(segment) > len(best):
                best = segment
    return best


def _match_hint_for_entry(
    query: str,
    entry: Entry,
    node_path: str,
    source_titles: list[str],
    match_hint_chars: int,
) -> tuple[str | None, list[str]]:
    """生成服务端可验证的匹配线索与命中字段；纯语义召回无命中时留空。"""
    q = _strip_query_frames(query).casefold()
    if not q:
        return None, []
    fields: list[str] = []
    hint: str | None = None
    title = entry.title or ""
    if title and q in title.casefold():
        fields.append("title")
        hint = f"标题命中「{_bound(title, 60)}」"
    elif title:
        common = _longest_common_substring(q, title)
        if len(common) >= 2:
            fields.append("title")
            hint = f"标题包含「{_bound(common, 60)}」"
    content = entry.content or ""
    if content and q in content.casefold():
        fields.append("content")
        position = content.casefold().find(q)
        start = max(0, position - 40)
        end = min(len(content), position + len(q) + 80)
        snippet = _bound(content[start:end], match_hint_chars)
        hint = hint or f"正文命中「…{snippet}…」"
    elif content:
        common = _longest_common_substring(q, content)
        if len(common) >= 2:
            fields.append("content")
            hint = hint or f"正文包含「{_bound(common, 60)}」"
    if node_path and q in node_path.casefold():
        fields.append("node")
        hint = hint or f"目录命中「{_bound(node_path, 60)}」"
    elif node_path:
        common = _longest_common_substring(q, node_path)
        if len(common) >= 2:
            fields.append("node")
            hint = hint or f"目录包含「{_bound(common, 60)}」"
    for title_item in source_titles:
        if title_item and q in title_item.casefold():
            fields.append("source")
            hint = hint or f"来源命中「{_bound(title_item, 60)}」"
        elif title_item:
            common = _longest_common_substring(q, title_item)
            if len(common) >= 2:
                fields.append("source")
                hint = hint or f"来源包含「{_bound(common, 60)}」"
    if hint is not None:
        hint = _bound(hint, match_hint_chars)
    return hint, fields


def _completeness_for(
    *,
    scope_total: int,
    candidates_count: int,
    persist_count: int,
    recall_limit: int,
    persist_limit: int,
    keyword_verified: bool,
    embedding_meta,
    assembly_failed: bool,
    capacity_truncated: bool = False,
) -> str:
    """完整性与分页正交：只有可证明穷尽时才返回 complete。"""
    if assembly_failed:
        return RESULT_COMPLETENESS_UNKNOWN
    if (
        scope_total > recall_limit
        or candidates_count > persist_limit
        or capacity_truncated
    ):
        return RESULT_COMPLETENESS_LIMITED
    # embedding 成功扩展语义召回时无法证明穷尽
    embedding_used = bool(
        embedding_meta is not None and not embedding_meta.is_fallback
    )
    if embedding_used:
        return RESULT_COMPLETENESS_LIMITED
    # 确定性关键词扫描覆盖全部范围内对象：结果集可证明穷尽
    if persist_count == 0 or keyword_verified:
        return RESULT_COMPLETENESS_COMPLETE
    return RESULT_COMPLETENESS_LIMITED


async def _assemble_items(
    db: AsyncSession,
    ctx,
    ordered_entries: list[Entry],
    query: str,
    *,
    excerpt_chars: int,
    node_path_chars: int,
    match_hint_chars: int,
) -> tuple[list[KnowledgeEntryResultItemOut], list[int]]:
    """批量装配结果项：项目/目录/证据关系批量加载，避免 N+1。"""
    path_by_node: dict[int, str] = {}
    project_ids = {entry.project_id for entry in ordered_entries if entry.project_id}
    for project_id in project_ids:
        path_by_node.update(await build_node_path_map(db, project_id))

    items: list[KnowledgeEntryResultItemOut] = []
    unavailable: list[int] = []
    for entry in ordered_entries:
        if ctx.scope_type == SCOPE_PROJECT and entry.project_id != ctx.project_id:
            unavailable.append(entry.id)
            continue
        source_titles = [
            item.source.title if item.source else ""
            for item in entry.evidences
        ]
        hint, matched_fields = _match_hint_for_entry(
            query,
            entry,
            path_by_node.get(entry.node_id, ""),
            source_titles,
            match_hint_chars,
        )
        items.append(
            KnowledgeEntryResultItemOut(
                entry_id=entry.id,
                title=entry.title,
                excerpt=_content_excerpt(
                    entry.content or "",
                    query,
                    excerpt_chars,
                ),
                project_id=entry.project_id,
                project_name=entry.project.name if entry.project else None,
                node_id=entry.node_id,
                node_path=_bound(
                    path_by_node.get(entry.node_id, ""),
                    node_path_chars,
                ),
                main_type=entry.main_type,
                info_nature=entry.info_nature,
                updated_at=entry.updated_at,
                source_count=len(entry.evidences),
                fingerprint=entry_fingerprint(entry_baseline(entry)),
                match_hint=hint,
                matched_fields=matched_fields,
            )
        )
    return items, unavailable
