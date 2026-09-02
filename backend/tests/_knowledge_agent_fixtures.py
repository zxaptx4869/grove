"""知识 Agent 测试共享数据夹具（不会被 pytest 直接收集）。"""

import uuid

from app.models import (
    Attachment,
    Entry,
    EntrySourceEvidence,
    Node,
    Project,
    Source,
    User,
    Workspace,
    WorkspaceMember,
)


async def create_user(db, prefix: str = "夹具") -> User:
    """创建独立用户。"""
    username = f"{prefix}_{uuid.uuid4().hex[:10]}"
    user = User(username=username, password_hash="x")
    db.add(user)
    await db.flush()
    return user


async def create_workspace(db, user: User) -> Workspace:
    """创建用户专属 Workspace。"""
    workspace = Workspace(name=f"{user.username} 的空间")
    db.add(workspace)
    await db.flush()
    db.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="owner"))
    await db.flush()
    return workspace


async def create_project(
    db,
    workspace: Workspace,
    name: str = "项目",
) -> Project:
    """创建项目与根节点。"""
    project = Project(
        workspace_id=workspace.id,
        name=name,
        template="empty",
        status="active",
    )
    db.add(project)
    await db.flush()
    node = Node(project_id=project.id, parent_id=None, name="根", position=0)
    db.add(node)
    await db.flush()
    return project


async def create_child_node(db, project: Project, name: str) -> Node:
    """创建项目子节点。"""
    node = Node(project_id=project.id, parent_id=None, name=name, position=0)
    db.add(node)
    await db.flush()
    return node


async def create_source_attachment(
    db,
    workspace: Workspace,
    project: Project,
    *,
    title: str = "来源",
    text_content: str | None = None,
    ocr_text: str | None = None,
) -> tuple[Source, Attachment]:
    """创建 Source 与 Attachment。"""
    source = Source(
        workspace_id=workspace.id,
        project_id=project.id,
        title=title,
        status="done",
    )
    db.add(source)
    await db.flush()
    attachment = Attachment(
        source_id=source.id,
        kind="text" if text_content else "image",
        position=0,
        text_content=text_content,
        ocr_text=ocr_text,
    )
    db.add(attachment)
    await db.flush()
    return source, attachment


async def create_entry_with_evidence(
    db,
    project: Project,
    node: Node,
    source: Source,
    attachment: Attachment,
    *,
    title: str = "闭水试验",
    content: str = "闭水试验通常持续 24 小时。",
    quote: str | None = None,
    main_type: str = "knowledge",
    info_nature: str | None = None,
) -> Entry:
    """创建已确认 Entry 与真实来源证据（quote 为候选引用片段）。"""
    entry = Entry(
        project_id=project.id,
        node_id=node.id,
        title=title,
        content=content,
        main_type=main_type,
        info_nature=info_nature,
    )
    db.add(entry)
    await db.flush()
    db.add(
        EntrySourceEvidence(
            entry_id=entry.id,
            source_id=source.id,
            attachment_id=attachment.id,
            quote=quote,
        )
    )
    await db.flush()
    return entry
