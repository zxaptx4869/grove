"""实验 Agent 的项目介绍快照读取；不创建上下文、不调度刷新。"""

from sqlalchemy import select

from app.db.session import async_session_factory
from app.models import Project, ProjectContext, WorkspaceMember
from app.services.project_context import _assemble_out


async def read_project_material(workspace_id: int, user_id: int, project_name: str) -> dict:
    """按当前成员权限读取唯一项目；同名歧义不能由模型猜测消解。"""
    async with async_session_factory() as db:
        member = await db.scalar(select(WorkspaceMember.id).where(
            WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.user_id == user_id,
        ))
        if member is None:
            raise ValueError("当前用户没有 Workspace 访问权限")
        projects = (await db.scalars(select(Project).where(
            Project.workspace_id == workspace_id, Project.name == project_name,
        ))).all()
        if len(projects) != 1:
            raise ValueError("项目不存在、不可访问或名称不唯一")
        project = projects[0]
        context = await db.scalar(select(ProjectContext).where(
            ProjectContext.project_id == project.id,
        ))
        snapshot = None
        if context is not None:
            assembled = (await _assemble_out(project, context)).model_dump(mode="json")
            snapshot = {key: assembled[key] for key in (
                "project_summary", "current_focus", "corrections", "generated_at", "version",
                "status", "provider", "model", "is_fallback",
            )}
            snapshot["refresh_pending"] = context.refresh_due_at is not None
        return {
            "project_id": project.id, "project_name": project.name,
            "lifecycle_status": project.status, "user_description": project.description,
            "saved_context": snapshot,
            "basis": ("背景目标由用户填写；上下文是已保存派生摘要，已应用用户纠正，"
                      "不是正式知识或来源原文"),
        }


def project_material_text(payload: dict) -> str:
    """合法项目句柄的确定性文本投影，不制造新的列表卡片。"""
    description = payload.get("user_description") or "尚未填写背景与目标。"
    parts = [f"{payload['project_name']}：{description}"]
    context = payload.get("saved_context")
    if context:
        parts.extend(str(context[key]) for key in ("project_summary", "current_focus")
                     if context.get(key))
        parts.append(
            f"以上上下文为已保存摘要（状态：{context['status']}，版本：{context['version']}，"
            f"生成时间：{context.get('generated_at') or '未知'}），不代表实时进展。"
        )
        if context.get("is_fallback"):
            parts.append("该上下文使用了降级生成结果。")
        if context.get("refresh_pending"):
            parts.append("项目上下文待刷新。")
    else:
        parts.append("尚无已保存的项目上下文。")
    return "\n\n".join(parts)
