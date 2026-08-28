"""Reader 问答 API。

兼容边界：本项目在知识 Agent 底座（/api/knowledge-agent）上线后仍保留旧 Reader
端点，供现有 Web 页面在迁移前继续使用；新知识 Agent 协议不依赖本端点，也不在本
change 中删除或代理。后续 Web 接入 change 完成迁移与人工验收后，再单独移除。
"""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import DbSession, get_current_workspace
from app.models import Workspace
from app.schemas.candidate import CandidateOut
from app.schemas.reader import ReaderAnswerOut, ReaderAskRequest, ReaderSaveRequest
from app.services.reader import ask_reader, save_answer_as_candidate

router = APIRouter(prefix="/api/projects", tags=["reader"])
CurrentWorkspace = Annotated[Workspace, Depends(get_current_workspace)]


@router.post("/{project_id}/reader/ask", response_model=ReaderAnswerOut)
async def reader_ask_endpoint(
    project_id: int,
    payload: ReaderAskRequest,
    db: DbSession,
    workspace: CurrentWorkspace,
) -> ReaderAnswerOut:
    """节点或项目范围的 AI 阅读问答。"""
    result = await ask_reader(db, workspace.id, project_id, payload)
    await db.commit()
    return result


@router.post("/{project_id}/reader/save-candidate", response_model=CandidateOut)
async def reader_save_candidate_endpoint(
    project_id: int,
    payload: ReaderSaveRequest,
    db: DbSession,
    workspace: CurrentWorkspace,
) -> CandidateOut:
    """把 AI 阅读回答保存为待采纳 Candidate。"""
    candidate = await save_answer_as_candidate(db, workspace.id, project_id, payload)
    await db.commit()
    return candidate
