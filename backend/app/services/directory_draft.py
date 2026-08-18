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
    run_directory_refine,
)
from app.db.session import async_session_factory
from app.models import Node, Project, ProjectContext
from app.models.directory_draft import (
    DRAFT_AWAITING_INPUT,
    DRAFT_CLARIFY,
    DRAFT_CONFIRMED,
    DRAFT_DISCARDED,
    DRAFT_DRAFTING,
    DRAFT_FAILED,
    DRAFT_GENERATE,
    DRAFT_PENDING_CONFIRM,
    DirectoryDraft,
    DirectoryDraftMessage,
    DirectoryDraftNode,
)
from app.schemas.directory_draft import (
    ClarifyQuestionOut,
    DraftMessageOut,
    DraftNodeOut,
    DraftOut,
)
from app.services.project_context import schedule_refresh

logger = logging.getLogger(__name__)

MAX_DRAFT_NODES = 200
MAX_CONVERSATION_ROUNDS = 30


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
) -> DraftOut:
    """组装草稿响应。"""
    messages = messages or []
    return DraftOut(
        id=draft.id,
        project_id=draft.project_id,
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


async def _build_context_text(db: AsyncSession, project: Project) -> str:
    """组装 Directory Agent 输入：项目说明 + Project Context 快照。"""
    parts = [f"项目：{project.name}"]
    parts.append(f"项目说明：{project.description or '（未填写）'}")
    context = (
        await db.execute(
            select(ProjectContext).where(ProjectContext.project_id == project.id)
        )
    ).scalar_one_or_none()
    if context is not None:
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
    draft.next_action = DRAFT_GENERATE
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
            if draft.next_action == DRAFT_CLARIFY:
                await run_clarify_step(db, draft, project)
            else:
                await run_generate_step(db, draft, project)
            draft.claimed_at = None
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
        await _append_draft_message(
            db,
            draft.id,
            "assistant",
            result.reply_text.strip() or "（已收到你的消息）",
        )
    return draft
