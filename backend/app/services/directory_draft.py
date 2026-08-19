"""Directory Draft 起草服务：澄清、生成、编辑与应用。"""

import json
import logging
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.directory import (
    DirectoryNodeDraft,
    run_directory_clarify,
    run_directory_draft,
    run_directory_expand,
    run_directory_refine,
)
from app.db.session import async_session_factory
from app.models import Entry, Node, Project, ProjectContext
from app.models.directory_draft import (
    DRAFT_AWAITING_INPUT,
    DRAFT_CLARIFY,
    DRAFT_CONFIRMED,
    DRAFT_DISCARDED,
    DRAFT_DRAFTING,
    DRAFT_FAILED,
    DRAFT_GENERATE,
    DRAFT_KIND_EXPAND,
    DRAFT_PENDING_CONFIRM,
    DirectoryDraft,
    DirectoryDraftMessage,
    DirectoryDraftNode,
)
from app.schemas.directory_draft import (
    ClarifyQuestionOut,
    DraftDiffNodeOut,
    DraftMessageOut,
    DraftNodeOut,
    DraftOut,
)
from app.services.nodes import (
    subtree_ids_in_memory,
    subtree_node_ids,
)
from app.services.project_context import schedule_refresh

logger = logging.getLogger(__name__)

MAX_DRAFT_NODES = 200
MAX_CONVERSATION_ROUNDS = 30
MAX_EXPAND_ENTRIES = 40
MAX_EXPAND_ENTRY_LENGTH = 200
MAX_EXPAND_ADDED_NODES = 30
MAX_EXPAND_ADDED_DEPTH = 5


def _parse_clarify(raw: str | None) -> list[ClarifyQuestionOut]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    result = []
    for item in data if isinstance(data, list) else []:
        if isinstance(item, dict):
            result.append(
                ClarifyQuestionOut(
                    id=str(item.get("id", "")),
                    text=str(item.get("text", "")),
                    options=[str(option) for option in item.get("options", [])],
                    multiple=bool(item.get("multiple", False)),
                )
            )
    return result


def _answers_text(raw: str | None) -> str:
    if not raw:
        return ""
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return ""
    lines = []
    for key, value in (data or {}).items():
        if isinstance(value, list):
            joined = "、".join(str(item) for item in value)
        else:
            joined = str(value)
        if joined:
            lines.append(f"{key}: {joined}")
    return "\n".join(lines)


def draft_out(
    draft: DirectoryDraft,
    nodes: list[DirectoryDraftNode],
    messages: list[DirectoryDraftMessage] | None = None,
    diff: list[DraftDiffNodeOut] | None = None,
) -> DraftOut:
    """组装草稿响应。"""
    messages = messages or []
    diff = diff or []
    return DraftOut(
        id=draft.id,
        project_id=draft.project_id,
        kind=draft.kind,
        target_node_id=draft.target_node_id,
        status=draft.status,
        next_action=draft.next_action,
        clarify_batches=draft.clarify_batches,
        clarify=_parse_clarify(draft.clarify_json),
        nodes=[
            DraftNodeOut(
                id=node.id,
                parent_id=node.parent_id,
                name=node.name,
                description=node.description,
                position=node.position,
                selected=node.selected,
            )
            for node in sorted(nodes, key=lambda item: item.position)
        ],
        messages=[
            DraftMessageOut(
                id=message.id,
                role=message.role,
                content=message.content,
                created_at=message.created_at,
            )
            for message in messages
        ],
        diff=diff,
        provider=draft.provider,
        model=draft.model,
        is_fallback=draft.is_fallback,
        last_error=draft.last_error,
        created_at=draft.created_at,
        updated_at=draft.updated_at,
    )


async def get_active_draft(
    db: AsyncSession,
    project_id: int,
) -> DirectoryDraft | None:
    """返回项目活跃草稿。"""
    return (
        await db.execute(
            select(DirectoryDraft)
            .where(
                DirectoryDraft.project_id == project_id,
                DirectoryDraft.status.in_(
                    [
                        DRAFT_DRAFTING,
                        DRAFT_AWAITING_INPUT,
                        DRAFT_PENDING_CONFIRM,
                        DRAFT_FAILED,
                    ]
                ),
            )
            .order_by(DirectoryDraft.updated_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _load_project_context(db: AsyncSession, project_id: int) -> ProjectContext | None:
    """读取项目上下文快照。"""
    return (
        await db.execute(
            select(ProjectContext).where(ProjectContext.project_id == project_id)
        )
    ).scalar_one_or_none()


def _append_snapshot_parts(parts: list[str], context: ProjectContext | None) -> None:
    """把 Project Context 快照的关键字段追加到 Agent 输入。"""
    if context is None:
        return
    if context.project_summary:
        parts.append(f"项目概要：{context.project_summary}")
    if context.current_focus:
        parts.append(f"当前关注：{context.current_focus}")
    try:
        topics = json.loads(context.directory_topics or "[]")
        if topics:
            parts.append("目录主题：" + "、".join(str(item) for item in topics))
    except json.JSONDecodeError:
        pass
    try:
        themes = json.loads(context.recent_themes or "[]")
        if themes:
            parts.append("近期主题：" + "、".join(str(item) for item in themes))
    except json.JSONDecodeError:
        pass


async def _build_context_text(db: AsyncSession, project: Project) -> str:
    """组装 Directory Agent 输入：项目说明 + Project Context 快照。"""
    parts = [f"项目：{project.name}"]
    parts.append(f"项目说明：{project.description or '（未填写）'}")
    _append_snapshot_parts(parts, await _load_project_context(db, project.id))
    return "\n".join(parts)


def _node_path(nodes: list[Node], node: Node) -> str:
    """计算节点祖先路径文本。"""
    by_id = {item.id: item for item in nodes}
    path: list[str] = []
    current: Node | None = node
    while current is not None:
        path.append(current.name)
        current = by_id.get(current.parent_id) if current.parent_id is not None else None
    return " / ".join(reversed(path))


def _subtree_lines(
    children_by_parent: dict[int | None, list[Node]],
    parent_id: int | None,
    depth: int,
    max_depth: int,
) -> list[str]:
    """把现有子树渲染成缩进文本（用于 Agent 输入）。"""
    lines: list[str] = []
    if depth > max_depth:
        return lines
    for node in sorted(
        children_by_parent.get(parent_id, []),
        key=lambda item: item.position,
    ):
        desc = f"：{node.description}" if node.description else ""
        lines.append(f"{'  ' * depth}- {node.name}{desc}")
        lines.extend(
            _subtree_lines(children_by_parent, node.id, depth + 1, max_depth)
        )
    return lines


async def _build_expand_context(
    db: AsyncSession,
    project: Project,
    target: Node,
) -> str:
    """组装节点拓展输入：目标节点 + 现有子树 + 快照 + 相关 Entry。"""
    parts = [f"项目：{project.name}"]
    parts.append(f"项目说明：{project.description or '（未填写）'}")
    _append_snapshot_parts(parts, await _load_project_context(db, project.id))

    all_nodes = list(
        (
            await db.execute(
                select(Node).where(Node.project_id == project.id)
            )
        ).scalars().all()
    )
    children_by_parent: dict[int | None, list[Node]] = {}
    for node in all_nodes:
        children_by_parent.setdefault(node.parent_id, []).append(node)
    parts.append(f"目标节点路径：{_node_path(all_nodes, target)}")
    parts.append(f"目标节点说明：{target.description or '（未填写）'}")
    existing = _subtree_lines(children_by_parent, target.id, 0, 2)
    if existing:
        parts.append("目标节点现有子节点：\n" + "\n".join(existing))
    else:
        parts.append("目标节点暂无子节点")

    subtree_ids = await subtree_node_ids(db, project.id, target.id)
    entries = list(
        (
            await db.execute(
                select(Entry)
                .where(Entry.project_id == project.id, Entry.node_id.in_(subtree_ids))
                .order_by(Entry.updated_at.desc())
                .limit(MAX_EXPAND_ENTRIES)
            )
        ).scalars().all()
    )
    if entries:
        lines = []
        for entry in entries:
            content = entry.content or ""
            truncated = len(content) > MAX_EXPAND_ENTRY_LENGTH
            content = content[:MAX_EXPAND_ENTRY_LENGTH]
            suffix = "…（已截断）" if truncated else ""
            lines.append(f"- [{entry.title}]（{entry.main_type}）：{content}{suffix}")
        parts.append(
            "相关 Entry（目标节点子树内，最多 "
            f"{MAX_EXPAND_ENTRIES} 条）：\n" + "\n".join(lines)
        )
        if len(entries) >= MAX_EXPAND_ENTRIES:
            parts.append("（相关知识较多，仅取最近 40 条，其余未展示）")
    else:
        parts.append("目标节点子树暂无已确认 Entry")
    return "\n".join(parts)


def _flatten_nodes(roots: list[DirectoryNodeDraft]) -> list[dict]:
    """把嵌套候选树拍平成带临时引用的列表。"""
    items: list[dict] = []

    def walk(nodes: list[DirectoryNodeDraft], parent_ref: int | None) -> None:
        for position, node in enumerate(nodes):
            ref = len(items)
            items.append(
                {
                    "ref": ref,
                    "name": node.name,
                    "description": node.description,
                    "parent_ref": parent_ref,
                    "position": position,
                    "selected": bool(getattr(node, "selected", True)),
                }
            )
            walk(node.children, ref)

    walk(roots, None)
    return items


async def _replace_draft_nodes(
    db: AsyncSession,
    draft: DirectoryDraft,
    roots: list[DirectoryNodeDraft],
) -> None:
    """全量替换草稿节点（删除旧节点后重建）。"""
    await db.execute(delete(DirectoryDraftNode).where(DirectoryDraftNode.draft_id == draft.id))
    items = _flatten_nodes(roots)
    if not items:
        return
    created: list[DirectoryDraftNode] = []
    for item in items:
        node = DirectoryDraftNode(
            draft_id=draft.id,
            name=item["name"],
            description=item["description"],
            position=item["position"],
            selected=item["selected"],
        )
        db.add(node)
        created.append(node)
    await db.flush()
    for node, item in zip(created, items, strict=True):
        if item["parent_ref"] is not None:
            node.parent_id = created[item["parent_ref"]].id


async def list_draft_messages(
    db: AsyncSession,
    draft_id: int,
) -> list[DirectoryDraftMessage]:
    """按时间顺序返回草稿会话消息。"""
    return list(
        (
            await db.execute(
                select(DirectoryDraftMessage)
                .where(DirectoryDraftMessage.draft_id == draft_id)
                .order_by(DirectoryDraftMessage.created_at, DirectoryDraftMessage.id)
            )
        ).scalars().all()
    )


async def _append_draft_message(
    db: AsyncSession,
    draft_id: int,
    role: str,
    content: str,
) -> None:
    db.add(
        DirectoryDraftMessage(
            draft_id=draft_id,
            role=role,
            content=content,
        )
    )


async def _draft_tree_json(db: AsyncSession, draft: DirectoryDraft) -> str:
    """把草稿节点序列化为嵌套 JSON 树。"""
    nodes = (
        await db.execute(
            select(DirectoryDraftNode).where(DirectoryDraftNode.draft_id == draft.id)
        )
    ).scalars().all()
    children_by_parent: dict[int | None, list[DirectoryDraftNode]] = {}
    for node in nodes:
        children_by_parent.setdefault(node.parent_id, []).append(node)

    def build(parent_id: int | None) -> list[dict]:
        result = []
        for node in sorted(
            children_by_parent.get(parent_id, []),
            key=lambda item: item.position,
        ):
            result.append(
                {
                    "name": node.name,
                    "description": node.description,
                    "children": build(node.id),
                }
            )
        return result

    return json.dumps(build(None), ensure_ascii=False)


def _count_tree(nodes: list[DirectoryNodeDraft]) -> int:
    return sum(1 + _count_tree(node.children) for node in nodes)


async def expansion_diff(
    db: AsyncSession,
    draft: DirectoryDraft,
) -> list[DraftDiffNodeOut]:
    """递归计算目标节点现有子树与草稿目标子树的差异。"""
    if draft.target_node_id is None:
        return []
    real_nodes = list(
        (
            await db.execute(
                select(Node).where(Node.project_id == draft.project_id)
            )
        ).scalars().all()
    )
    real_by_id = {node.id: node for node in real_nodes}
    real_children: dict[int | None, list[Node]] = {}
    children_ids: dict[int | None, list[int]] = {}
    for node in real_nodes:
        real_children.setdefault(node.parent_id, []).append(node)
        children_ids.setdefault(node.parent_id, []).append(node.id)
    for siblings in real_children.values():
        siblings.sort(key=lambda item: item.position)

    draft_nodes = list(
        (
            await db.execute(
                select(DirectoryDraftNode).where(
                    DirectoryDraftNode.draft_id == draft.id
                )
            )
        ).scalars().all()
    )
    draft_children: dict[int | None, list[DirectoryDraftNode]] = {}
    for node in draft_nodes:
        draft_children.setdefault(node.parent_id, []).append(node)
    for siblings in draft_children.values():
        siblings.sort(key=lambda item: item.position)

    removed_entries: list[DraftDiffNodeOut] = []

    async def diff_level(
        draft_siblings: list[DirectoryDraftNode],
        real_siblings: list[Node],
    ) -> list[DraftDiffNodeOut]:
        real_by_name = {
            node.name.strip().casefold(): node for node in real_siblings
        }
        result: list[DraftDiffNodeOut] = []
        matched: set[int] = set()
        for draft_node in draft_siblings:
            real = real_by_name.get(draft_node.name.strip().casefold())
            if real is not None:
                matched.add(real.id)
                result.append(
                    DraftDiffNodeOut(
                        kind="kept",
                        node_id=draft_node.id,
                        real_node_id=real.id,
                        name=draft_node.name,
                        description=draft_node.description,
                        children=await diff_level(
                            draft_children.get(draft_node.id, []),
                            real_children.get(real.id, []),
                        ),
                    )
                )
            else:
                result.append(
                    DraftDiffNodeOut(
                        kind="added",
                        node_id=draft_node.id,
                        real_node_id=None,
                        name=draft_node.name,
                        description=draft_node.description,
                        children=await diff_level(
                            draft_children.get(draft_node.id, []),
                            [],
                        ),
                    )
                )
        for real in real_siblings:
            if real.id in matched:
                continue
            entry = DraftDiffNodeOut(
                kind="removed",
                node_id=None,
                real_node_id=real.id,
                name=real.name,
                description=real.description,
                children=await diff_level(
                    [],
                    real_children.get(real.id, []),
                ),
            )
            removed_entries.append(entry)
            result.append(entry)
        return result

    target = real_by_id.get(draft.target_node_id)
    if target is None:
        return []
    diff = await diff_level(
        draft_children.get(None, []),
        real_children.get(target.id, []),
    )
    # 一次性批量统计建议移除子树的正式 Entry 数量，避免逐节点查询
    if removed_entries:
        removed_subtrees: dict[int, set[int]] = {}
        removed_ids_all: set[int] = set()
        for entry in removed_entries:
            if entry.real_node_id is None:
                continue
            ids = subtree_ids_in_memory(entry.real_node_id, children_ids)
            removed_subtrees[entry.real_node_id] = ids
            removed_ids_all.update(ids)
        counts: dict[int, int] = {}
        if removed_ids_all:
            rows = (
                await db.execute(
                    select(Entry.node_id, func.count())
                    .where(
                        Entry.project_id == draft.project_id,
                        Entry.node_id.in_(removed_ids_all),
                    )
                    .group_by(Entry.node_id)
                )
            ).all()
            counts = {node_id: count for node_id, count in rows}
        for entry in removed_entries:
            if entry.real_node_id is None:
                continue
            total = sum(
                counts.get(node_id, 0)
                for node_id in removed_subtrees[entry.real_node_id]
            )
            entry.blocked = total > 0
            entry.blocker_count = total
    return diff


async def run_generate_step(
    db: AsyncSession,
    draft: DirectoryDraft,
    project: Project,
) -> None:
    """运行起草步骤并写入候选树。"""
    context_text = await _build_context_text(db, project)
    answers = _answers_text(draft.clarify_answers_json)
    if answers:
        context_text = f"{context_text}\n\n用户澄清答案：\n{answers}"
    result, meta = await run_directory_draft(
        db,
        project.workspace_id,
        project,
        context_text,
    )
    await _replace_draft_nodes(db, draft, result.nodes)
    draft.provider = meta.provider
    draft.model = meta.model
    draft.is_fallback = meta.is_fallback
    draft.next_action = DRAFT_GENERATE
    draft.status = DRAFT_PENDING_CONFIRM
    draft.last_error = None
    if meta.is_fallback:
        logger.warning("Directory Draft 降级生成：provider=%s", meta.provider)


async def run_expand_step(
    db: AsyncSession,
    draft: DirectoryDraft,
    project: Project,
) -> None:
    """运行节点拓展步骤并写入完整目标子树。"""
    if draft.target_node_id is None:
        raise ValueError("节点拓展草稿缺少目标节点")
    target = await db.get(Node, draft.target_node_id)
    if target is None or target.project_id != project.id:
        draft.status = DRAFT_DISCARDED
        draft.last_error = "目标节点不存在，草稿已作废"
        return
    context_text = await _build_expand_context(db, project, target)
    result, meta = await run_directory_expand(
        db,
        project.workspace_id,
        project,
        context_text,
        target.name,
    )
    await _replace_draft_nodes(db, draft, result.nodes)
    draft.provider = meta.provider
    draft.model = meta.model
    draft.is_fallback = meta.is_fallback
    draft.next_action = DRAFT_GENERATE
    draft.status = DRAFT_PENDING_CONFIRM
    draft.last_error = None
    if meta.is_fallback:
        logger.warning("Directory Draft 节点拓展降级生成：provider=%s", meta.provider)


async def run_clarify_step(
    db: AsyncSession,
    draft: DirectoryDraft,
    project: Project,
) -> None:
    """运行澄清步骤；信息足够或超批次时直接生成。"""
    if draft.clarify_batches >= 2:
        await run_generate_step(db, draft, project)
        return
    context_text = await _build_context_text(db, project)
    answers = _answers_text(draft.clarify_answers_json)
    if answers:
        context_text = f"{context_text}\n\n用户澄清答案：\n{answers}"
    result, meta = await run_directory_clarify(
        db,
        project.workspace_id,
        project,
        context_text,
        draft.clarify_batches,
    )
    draft.provider = meta.provider
    draft.model = meta.model
    draft.is_fallback = meta.is_fallback
    if result.needs_more and result.questions:
        draft.clarify_json = json.dumps(
            [
                {
                    "id": question.id,
                    "text": question.text,
                    "options": question.options,
                    "multiple": question.multiple,
                }
                for question in result.questions
            ],
            ensure_ascii=False,
        )
        draft.status = DRAFT_AWAITING_INPUT
        draft.next_action = DRAFT_CLARIFY
        return
    draft.clarify_json = "[]"
    draft.next_action = DRAFT_GENERATE
    await run_generate_step(db, draft, project)


async def create_or_reuse_draft(
    db: AsyncSession,
    project: Project,
) -> DirectoryDraft:
    """创建或复用项目活跃草稿；失败草稿重置后复用。"""
    existing = await get_active_draft(db, project.id)
    if existing is not None:
        if existing.status == DRAFT_FAILED:
            existing.status = DRAFT_DRAFTING
            existing.next_action = DRAFT_CLARIFY
            existing.clarify_json = None
            existing.clarify_answers_json = None
            existing.clarify_batches = 0
            existing.conversation_rounds = 0
            existing.last_error = None
            existing.claimed_at = None
            await db.execute(
                delete(DirectoryDraftNode).where(
                    DirectoryDraftNode.draft_id == existing.id
                )
            )
            await db.execute(
                delete(DirectoryDraftMessage).where(
                    DirectoryDraftMessage.draft_id == existing.id
                )
            )
        return existing
    draft = DirectoryDraft(
        project_id=project.id,
        status=DRAFT_DRAFTING,
        next_action=DRAFT_CLARIFY,
    )
    db.add(draft)
    await db.flush()
    return draft


async def create_or_reuse_expand_draft(
    db: AsyncSession,
    project: Project,
    target_node: Node,
) -> DirectoryDraft:
    """创建或复用活跃草稿并发起节点拓展（覆盖时重置内容）。"""
    existing = await get_active_draft(db, project.id)
    if existing is not None:
        existing.kind = DRAFT_KIND_EXPAND
        existing.target_node_id = target_node.id
        existing.status = DRAFT_DRAFTING
        existing.next_action = DRAFT_GENERATE
        existing.clarify_json = None
        existing.clarify_answers_json = None
        existing.clarify_batches = 0
        existing.conversation_rounds = 0
        existing.last_error = None
        existing.provider = None
        existing.model = None
        existing.is_fallback = False
        existing.claimed_at = None
        await db.execute(
            delete(DirectoryDraftNode).where(
                DirectoryDraftNode.draft_id == existing.id
            )
        )
        await db.execute(
            delete(DirectoryDraftMessage).where(
                DirectoryDraftMessage.draft_id == existing.id
            )
        )
        return existing
    draft = DirectoryDraft(
        project_id=project.id,
        kind=DRAFT_KIND_EXPAND,
        target_node_id=target_node.id,
        status=DRAFT_DRAFTING,
        next_action=DRAFT_GENERATE,
    )
    db.add(draft)
    await db.flush()
    return draft


async def submit_clarify_answers(
    db: AsyncSession,
    draft: DirectoryDraft,
    project: Project,
    answers: dict[str, str | list[str]],
) -> DirectoryDraft:
    """保存澄清答案并生成候选树。"""
    if draft.status != DRAFT_AWAITING_INPUT:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="草稿当前不需要澄清")
    draft.clarify_answers_json = json.dumps(answers, ensure_ascii=False)
    draft.clarify_batches += 1
    draft.next_action = DRAFT_CLARIFY
    draft.status = DRAFT_DRAFTING
    draft.claimed_at = None
    return draft


async def claim_next_draft(db: AsyncSession) -> DirectoryDraft | None:
    """认领一个待处理的草稿步骤。"""
    draft = (
        await db.execute(
            select(DirectoryDraft)
            .where(
                DirectoryDraft.status == DRAFT_DRAFTING,
                DirectoryDraft.claimed_at.is_(None),
            )
            .order_by(DirectoryDraft.updated_at)
            .limit(1)
        )
    ).scalar_one_or_none()
    if draft is None:
        return None
    draft.claimed_at = datetime.now(UTC)
    return draft


async def process_next_draft_step() -> bool:
    """认领并处理一个草稿步骤，返回是否有步骤被处理。"""
    async with async_session_factory() as db:
        draft = await claim_next_draft(db)
        if draft is None:
            return False
        draft_id = draft.id
        project_id = draft.project_id
        await db.commit()

    async with async_session_factory() as db:
        draft = await db.get(DirectoryDraft, draft_id)
        project = await db.get(Project, project_id)
        if draft is None or project is None:
            return True
        try:
            if draft.kind == DRAFT_KIND_EXPAND:
                await run_expand_step(db, draft, project)
            elif draft.next_action == DRAFT_CLARIFY:
                await run_clarify_step(db, draft, project)
            else:
                await run_generate_step(db, draft, project)
            draft.claimed_at = None
            if draft.status != DRAFT_DISCARDED:
                draft.last_error = None
        except Exception as exc:  # noqa: BLE001
            logger.exception("处理目录草稿步骤失败：%s", draft_id)
            draft.status = DRAFT_FAILED
            draft.last_error = str(exc)[:2000]
            draft.claimed_at = None
        await db.commit()
    return True


async def update_draft_nodes(
    db: AsyncSession,
    draft: DirectoryDraft,
    roots: list[DirectoryNodeDraft],
) -> DirectoryDraft:
    """内联编辑：全量替换草稿节点树。"""
    if draft.status != DRAFT_PENDING_CONFIRM:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="草稿不在可编辑状态")
    await _replace_draft_nodes(db, draft, roots)
    return draft


async def apply_draft(
    db: AsyncSession,
    draft: DirectoryDraft,
    project: Project,
    removed_node_ids: list[int] | None = None,
) -> DirectoryDraft:
    """校验并原子应用草稿为正式目录。"""
    if draft.status != DRAFT_PENDING_CONFIRM:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="草稿不在待确认状态")
    nodes = (
        await db.execute(
            select(DirectoryDraftNode).where(DirectoryDraftNode.draft_id == draft.id)
        )
    ).scalars().all()
    if not nodes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="草稿为空")
    if len(nodes) > MAX_DRAFT_NODES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"草稿节点数超过上限 {MAX_DRAFT_NODES}",
        )
    if draft.kind == DRAFT_KIND_EXPAND:
        return await _apply_expand_draft(
            db,
            draft,
            project,
            removed_node_ids or [],
        )
    existing_count = (
        await db.execute(
            select(func.count()).select_from(Node).where(Node.project_id == project.id)
        )
    ).scalar_one()
    if existing_count > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="从零起草仅适用于空目录项目",
        )

    by_id = {node.id: node for node in nodes}
    children_by_parent: dict[int | None, list[DirectoryDraftNode]] = {}
    for node in nodes:
        if node.parent_id is not None and node.parent_id not in by_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="草稿包含非法父引用",
            )
        children_by_parent.setdefault(node.parent_id, []).append(node)

    position_counters: dict[int | None, int] = {}
    created_node_ids: dict[int, int] = {}

    async def create_from(parent_draft_id: int | None) -> None:
        for node in sorted(
            children_by_parent.get(parent_draft_id, []),
            key=lambda item: item.position,
        ):
            if not node.selected:
                continue
            formal_parent = (
                created_node_ids[node.parent_id] if node.parent_id is not None else None
            )
            position = position_counters.get(formal_parent, 0)
            formal = Node(
                project_id=project.id,
                parent_id=formal_parent,
                name=node.name,
                description=node.description,
                position=position,
            )
            db.add(formal)
            await db.flush()
            created_node_ids[node.id] = formal.id
            position_counters[formal_parent] = position + 1
            await create_from(node.id)

    await create_from(None)
    draft.status = DRAFT_CONFIRMED
    await schedule_refresh(db, project.id, "directory_changed")
    return draft


async def _apply_expand_draft(
    db: AsyncSession,
    draft: DirectoryDraft,
    project: Project,
    removed_node_ids: list[int],
) -> DirectoryDraft:
    """应用节点拓展草稿：创建新增、删除勾选的建议移除子树。"""
    if draft.target_node_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="拓展草稿缺少目标节点")
    target = await db.get(Node, draft.target_node_id)
    if target is None or target.project_id != project.id:
        draft.status = DRAFT_DISCARDED
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="目标节点已不存在，草稿已作废",
        )

    nodes = list(
        (
            await db.execute(
                select(DirectoryDraftNode).where(
                    DirectoryDraftNode.draft_id == draft.id
                )
            )
        ).scalars().all()
    )
    by_id = {node.id: node for node in nodes}
    children_by_parent: dict[int | None, list[DirectoryDraftNode]] = {}
    for node in nodes:
        if node.parent_id is not None and node.parent_id not in by_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="草稿包含非法父引用",
            )
        children_by_parent.setdefault(node.parent_id, []).append(node)
    selected_by_id = {node.id: node.selected for node in nodes}

    # 递归收集差异中的建议移除项
    diff = await expansion_diff(db, draft)
    removed_by_real: dict[int, DraftDiffNodeOut] = {}

    def collect_removed(entries: list[DraftDiffNodeOut]) -> None:
        for entry in entries:
            if entry.kind == "removed" and entry.real_node_id is not None:
                removed_by_real[entry.real_node_id] = entry
            collect_removed(entry.children)

    collect_removed(diff)

    # 校验勾选的移除项
    real_nodes = list(
        (
            await db.execute(
                select(Node).where(Node.project_id == project.id)
            )
        ).scalars().all()
    )
    real_by_id = {node.id: node for node in real_nodes}
    children_ids: dict[int | None, list[int]] = {}
    for node in real_nodes:
        children_ids.setdefault(node.parent_id, []).append(node.id)
    removal_roots: list[int] = []
    for real_id in removed_node_ids:
        entry = removed_by_real.get(real_id)
        if entry is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="所选移除节点不在 AI 建议移除范围内",
            )
        if entry.blocked:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"「{entry.name}」含 {entry.blocker_count} 条正式知识，无法移除",
            )
        ancestor_ids: set[int] = set()
        current = real_by_id.get(real_id)
        while current is not None and current.parent_id is not None:
            parent = real_by_id.get(current.parent_id)
            if parent is None:
                break
            ancestor_ids.add(parent.id)
            current = parent
        if ancestor_ids & set(removal_roots):
            continue
        removal_roots.append(real_id)

    # 校验新增数量与层级
    draft_depth: dict[int, int] = {}

    def depth_walk(parent_id: int | None, depth: int) -> None:
        for node in sorted(
            children_by_parent.get(parent_id, []),
            key=lambda item: item.position,
        ):
            draft_depth[node.id] = depth
            depth_walk(node.id, depth + 1)

    depth_walk(None, 1)
    added_ids: set[int | None] = set()

    def collect_added(entries: list[DraftDiffNodeOut]) -> None:
        for entry in entries:
            if entry.kind == "added":
                added_ids.add(entry.node_id)
            collect_added(entry.children)

    collect_added(diff)
    added_count = sum(
        1
        for draft_id in added_ids
        if draft_id is not None and selected_by_id.get(draft_id, False)
    )
    for draft_id in added_ids:
        if (
            draft_id is not None
            and selected_by_id.get(draft_id, False)
            and draft_depth.get(draft_id, 1) > MAX_EXPAND_ADDED_DEPTH
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"新增节点层级超过上限 {MAX_EXPAND_ADDED_DEPTH}",
            )
    if added_count > MAX_EXPAND_ADDED_NODES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"新增节点数超过上限 {MAX_EXPAND_ADDED_NODES}",
        )

    # 删除勾选的建议移除子树
    removal_all: set[int] = set()
    for real_id in removal_roots:
        removal_all.update(subtree_ids_in_memory(real_id, children_ids))
    if removal_all:
        await db.execute(delete(Node).where(Node.id.in_(removal_all)))
        await db.flush()

    # 重新加载实时节点，创建新增节点并映射保留节点
    real_nodes = list(
        (
            await db.execute(
                select(Node).where(Node.project_id == project.id)
            )
        ).scalars().all()
    )
    real_children: dict[int | None, list[Node]] = {}
    for node in real_nodes:
        real_children.setdefault(node.parent_id, []).append(node)
    for siblings in real_children.values():
        siblings.sort(key=lambda item: item.position)

    async def create_from(draft_parent_id: int | None, real_parent_id: int | None) -> None:
        for node in sorted(
            children_by_parent.get(draft_parent_id, []),
            key=lambda item: item.position,
        ):
            existing = next(
                (
                    real
                    for real in real_children.get(real_parent_id, [])
                    if real.name.strip().casefold() == node.name.strip().casefold()
                ),
                None,
            )
            if existing is not None:
                await create_from(node.id, existing.id)
                continue
            if not node.selected:
                continue
            siblings = real_children.get(real_parent_id, [])
            formal = Node(
                project_id=project.id,
                parent_id=real_parent_id,
                name=node.name,
                description=node.description,
                position=len(siblings),
            )
            db.add(formal)
            await db.flush()
            real_children.setdefault(real_parent_id, []).append(formal)
            await create_from(node.id, formal.id)

    await create_from(None, target.id)
    draft.status = DRAFT_CONFIRMED
    await schedule_refresh(db, project.id, "directory_changed")
    return draft


async def discard_draft(db: AsyncSession, draft: DirectoryDraft) -> DirectoryDraft:
    """丢弃草稿。"""
    draft.status = DRAFT_DISCARDED
    return draft


async def submit_draft_message(
    db: AsyncSession,
    draft: DirectoryDraft,
    project: Project,
    content: str,
) -> DirectoryDraft:
    """追加用户消息，调用 Agent 调整草稿并自动应用返回的候选树。"""
    if draft.status != DRAFT_PENDING_CONFIRM:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="草稿当前不能对话调整",
        )
    content = content.strip()
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="消息内容不能为空")
    if len(content) > 2000:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="消息最长 2000 字符")
    if draft.conversation_rounds >= MAX_CONVERSATION_ROUNDS:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"会话轮次已达上限（{MAX_CONVERSATION_ROUNDS}），请重新起草",
        )

    await _append_draft_message(db, draft.id, "user", content)
    draft.conversation_rounds += 1
    await db.flush()

    if draft.kind == DRAFT_KIND_EXPAND:
        if draft.target_node_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="拓展草稿缺少目标节点",
            )
        target = await db.get(Node, draft.target_node_id)
        if target is None or target.project_id != project.id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="目标节点已不存在，草稿已作废",
            )
        context_text = await _build_expand_context(db, project, target)
    else:
        context_text = await _build_context_text(db, project)
    tree_json = await _draft_tree_json(db, draft)
    messages = await list_draft_messages(db, draft.id)
    convo = [
        {"role": message.role, "content": message.content}
        for message in messages
    ]
    result, meta = await run_directory_refine(
        db,
        project.workspace_id,
        project,
        context_text,
        tree_json,
        convo,
    )
    draft.provider = meta.provider
    draft.model = meta.model
    draft.is_fallback = meta.is_fallback
    if meta.is_fallback:
        logger.warning("Directory Draft 对话降级：provider=%s", meta.provider)

    if result.tree is not None:
        await _replace_draft_nodes(db, draft, result.tree)
        node_count = _count_tree(result.tree)
        await _append_draft_message(
            db,
            draft.id,
            "assistant",
            result.reply_text.strip() or "（已更新目录草稿）",
        )
        await _append_draft_message(
            db,
            draft.id,
            "system",
            f"已应用目录，共 {node_count} 个节点",
        )
    else:
        reply_text = result.reply_text.strip()
        # 兜底：模型把内部字段（tree/null）写进回复时，替换为自然文案
        if "tree" in reply_text.lower() and "null" in reply_text.lower():
            reply_text = "已收到，当前草稿保持不变。"
        await _append_draft_message(
            db,
            draft.id,
            "assistant",
            reply_text or "（已收到你的消息）",
        )
    return draft
