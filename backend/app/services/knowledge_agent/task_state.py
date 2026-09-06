"""会话内有界任务版本、条件归并和实体核实；历史结果不作为事实。"""

import json
from time import perf_counter
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from app.agents.dialogue_task import QueryTaskDeltaDraft, TaskDecisionDraft
from app.core.config import get_settings
from app.models import KnowledgeAgentRun, KnowledgeConversation, KnowledgeMessage, Project
from app.services.knowledge_agent.dialogue_context import DialogueContext
from app.services.knowledge_agent.structured_query import normalize_structured_query_plan

PROTOCOL = "dialogue_task_v1"
KEY = "dialogue_task"


class TaskStateError(ValueError):
    """任务候选不可安全执行。"""


class StrictState(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProjectBinding(StrictState):
    project_id: int
    name: str


class TaskFrame(StrictState):
    handle: str
    origin_run_id: int
    parent: str | None = None
    depth: int = Field(default=0, ge=0, le=2)
    goal: str = Field(max_length=2000)
    plan: dict | None = None
    sources: dict = Field(default_factory=dict)
    basis: Literal["auto", "no_grove", "knowledge_only"] = "auto"
    basis_source: dict | None = None
    message_ids: list[int] = Field(default_factory=list, max_length=16)
    result_run_id: int | None = None
    context_version_id: int | None = None
    result_titles: list[str] = Field(default_factory=list, max_length=50)
    binding: ProjectBinding | None = None
    legacy: bool = False


class TaskState(StrictState):
    protocol: Literal["dialogue_task_v1"] = PROTOCOL
    phase: Literal["waiting", "selected", "planned", "committed", "pending"] = "waiting"
    epoch: int = 0
    hard_reset: bool = False
    pool: list[TaskFrame] = Field(default_factory=list, max_length=5)
    frame: TaskFrame | None = None
    operation: str | None = None
    input: dict = Field(default_factory=dict)
    changes: dict | None = None
    pending_question: str | None = None
    statement_message_ids: list[int] = Field(default_factory=list, max_length=16)
    metadata_audit: dict = Field(default_factory=dict)


def read_state(run) -> TaskState | None:
    raw = json.loads(getattr(run, "context_meta_json", None) or "{}")
    if KEY not in raw:
        return None
    try:
        return TaskState.model_validate(raw[KEY])
    except ValueError as exc:
        raise TaskStateError("任务状态版本未知或内容损坏，不能按旧语义恢复") from exc


def write_state(run, state: TaskState) -> None:
    meta = json.loads(getattr(run, "context_meta_json", None) or "{}")
    meta[KEY] = state.model_dump(mode="json")
    run.context_meta_json = json.dumps(meta, ensure_ascii=False)


def public_frame(frame: TaskFrame) -> dict:
    return frame.model_dump(
        exclude={
            "binding",
            "origin_run_id",
            "result_run_id",
            "message_ids",
            "context_version_id",
        }
    )


async def load_task_dialogue(db, run) -> DialogueContext:
    """只在当前范围的显式边界内装配任务；自动切题保留可恢复意图。"""
    conversation = await db.get(KnowledgeConversation, run.conversation_id)
    if not conversation or (
        conversation.workspace_id != run.workspace_id
        or conversation.owner_user_id != run.owner_user_id
    ):
        raise TaskStateError("任务不属于当前对话")
    state = read_state(run)
    if state is None:
        raise TaskStateError("缺少本轮任务协议")
    boundary = (
        await db.execute(
            select(func.max(KnowledgeMessage.id)).where(
                KnowledgeMessage.conversation_id == run.conversation_id,
                KnowledgeMessage.message_type == "scope_change",
                KnowledgeMessage.id < run.user_message_id,
            )
        )
    ).scalar() or 0
    recent = (
        (
            await db.execute(
                select(KnowledgeAgentRun)
                .where(
                    KnowledgeAgentRun.conversation_id == run.conversation_id,
                    KnowledgeAgentRun.workspace_id == run.workspace_id,
                    KnowledgeAgentRun.owner_user_id == run.owner_user_id,
                    KnowledgeAgentRun.scope_type == run.scope_type,
                    KnowledgeAgentRun.project_id == run.project_id,
                    KnowledgeAgentRun.user_message_id > boundary,
                    KnowledgeAgentRun.user_message_id < run.user_message_id,
                    KnowledgeAgentRun.run_kind == "answer",
                )
                .order_by(KnowledgeAgentRun.user_message_id.desc())
                .limit(32)
            )
        )
        .scalars()
        .all()
    )
    selected = []
    for previous in recent:
        previous_state = read_state(previous)
        selected.append(previous)
        if previous.request_context_mode == "new_topic" or (
            previous_state and previous_state.hard_reset
        ):
            boundary = max(boundary, previous.user_message_id)
            break
    if run.request_context_mode == "new_topic":
        selected = []
        boundary = run.user_message_id
        state.hard_reset = True
    state.epoch = boundary
    pool: list[TaskFrame] = []
    for previous in reversed(selected):
        saved = read_state(previous)
        if saved and saved.hard_reset:
            pool = []
        if saved and saved.phase == "committed" and previous.status in {"completed", "partial"}:
            pool = saved.pool
        elif saved is None and previous.status in {"completed", "partial"}:
            if previous.context_decision == "clarify":
                continue
            from app.services.knowledge_agent.basis import (
                contains_knowledge_only_restriction,
                contains_no_grove_restriction,
            )

            message = await db.get(KnowledgeMessage, previous.user_message_id)
            original = message.content if message else ""
            basis = "auto"
            if (
                previous.request_basis_mode == "knowledge_only"
                or contains_knowledge_only_restriction(original)
            ):
                basis = "knowledge_only"
            elif contains_no_grove_restriction(original):
                basis = "no_grove"
            plan = json.loads(previous.structured_query_plan_json or "null")
            pool.append(
                TaskFrame(
                    handle=f"t{previous.id}",
                    origin_run_id=previous.id,
                    goal=previous.standalone_query or previous.topic_label or "先前任务",
                    plan=plan,
                    message_ids=[previous.user_message_id],
                    result_run_id=previous.id,
                    context_version_id=previous.output_context_version_id,
                    basis=basis,
                    basis_source={"message_id": previous.user_message_id, "origin": "legacy"}
                    if basis != "auto"
                    else None,
                    legacy=True,
                )
            )
            pool = pool[-5:]
    # 逐个验证持久化句柄的归属，不能因同名或损坏的跨任务引用扩大权限。
    valid_pool = []
    for frame in pool:
        origin = await db.get(KnowledgeAgentRun, frame.origin_run_id)
        if origin and (
            origin.conversation_id == run.conversation_id
            and origin.owner_user_id == run.owner_user_id
            and origin.workspace_id == run.workspace_id
            and origin.scope_type == run.scope_type
            and origin.project_id == run.project_id
            and boundary <= origin.user_message_id < run.user_message_id
        ):
            valid_pool.append(frame)
    state.pool = valid_pool[-5:]
    settings = get_settings()
    messages = []
    if selected:
        messages = (
            (
                await db.execute(
                    select(KnowledgeMessage)
                    .where(
                        KnowledgeMessage.conversation_id == run.conversation_id,
                        KnowledgeMessage.run_id.in_([r.id for r in selected]),
                        KnowledgeMessage.id >= boundary,
                        KnowledgeMessage.id < run.user_message_id,
                        KnowledgeMessage.role.in_(["user", "assistant"]),
                        KnowledgeMessage.scope_type == run.scope_type,
                        KnowledgeMessage.project_id == run.project_id,
                    )
                    .order_by(KnowledgeMessage.id.desc())
                    .limit(settings.knowledge_agent_history_limit)
                )
            )
            .scalars()
            .all()
        )
    history = [
        {
            "role": m.role,
            "content": m.content[: settings.knowledge_agent_history_message_chars],
            "handle": f"m{m.id}",
        }
        for m in reversed(messages)
        if m.content.strip()
    ]
    pending = None
    if selected:
        last = selected[0]
        last_state = read_state(last)
        if last_state and last_state.phase != "committed":
            pending = {
                "question": last_state.pending_question,
                "request": last_state.input.get("current_message"),
                "task_handle": (
                    last_state.frame.handle
                    if last_state.frame
                    and any(f.handle == last_state.frame.handle for f in state.pool)
                    else None
                ),
            }
    payload = {
        "protocol": PROTOCOL,
        "tasks": [public_frame(f) for f in reversed(state.pool)],
        "pending": pending,
        "history": history,
    }
    initial_history, initial_pool = len(history), len(state.pool)
    while (
        len(json.dumps(payload, ensure_ascii=False).encode())
        > settings.knowledge_agent_task_context_bytes
    ):
        if history:
            history.pop(0)
        elif len(state.pool) > 1:
            state.pool.pop(0)
            payload["tasks"] = [public_frame(f) for f in reversed(state.pool)]
        else:
            raise TaskStateError("任务上下文超过预算，请明确本轮需要的条件")
    state.metadata_audit["trimmed_history"] = initial_history - len(history)
    state.metadata_audit["trimmed_tasks"] = initial_pool - len(state.pool)
    state.input = payload
    write_state(run, state)
    return DialogueContext(
        history=history,
        message_ids=[int(m["handle"][1:]) for m in history],
        topic_label=state.pool[-1].goal if state.pool else None,
        task=payload,
    )


async def select_task(
    db, run, draft: TaskDecisionDraft, current_message: str
) -> tuple[TaskState, list[int]]:
    state = read_state(run)
    if state is None:
        raise TaskStateError("缺少任务状态")
    state.input["current_message"] = current_message
    base = next((f for f in state.pool if f.handle == draft.task_handle), None)
    if draft.task_handle and base is None:
        raise TaskStateError("所选任务已经不可用，请说明需要恢复的任务")
    operation = draft.operation
    if run.request_context_mode == "new_topic" or draft.reset_quote:
        if draft.reset_quote and draft.reset_quote not in current_message:
            raise TaskStateError("重置请求缺少当前消息依据")
        operation, base = "start", None
        state.pool = []
        state.epoch = run.user_message_id
        state.hard_reset = True
    if run.request_context_mode == "continue" and operation == "start":
        raise TaskStateError("当前要求继续任务，请明确需要继续的主题")
    if operation in {"continue", "branch", "resume"} and base is None:
        raise TaskStateError("缺少可继续的任务，请补充具体对象")
    if operation == "start":
        base = None
    frame = (
        base.model_copy(deep=True)
        if base
        else TaskFrame(
            handle=f"t{run.id}",
            origin_run_id=run.id,
            goal=draft.topic_label or current_message[:2000],
        )
    )
    if operation == "branch":
        if frame.depth >= 2:
            raise TaskStateError("任务深入超过当前上限，请直接说明本轮筛选条件")
        frame.parent = frame.handle
        frame.handle = f"t{run.id}"
        frame.origin_run_id = run.id
        frame.depth += 1
    frame.goal = (draft.standalone_query or draft.topic_label or current_message)[:2000]
    if draft.basis != "inherit":
        if not draft.basis_quote or draft.basis_quote not in current_message:
            raise TaskStateError("依据限制变更缺少当前消息来源")
        frame.basis = draft.basis
        frame.basis_source = {"message_id": run.user_message_id, "quote": draft.basis_quote}
    state.statement_message_ids = list(frame.message_ids[-15:])
    frame.message_ids = list(dict.fromkeys([*frame.message_ids, run.user_message_id]))[-16:]
    state.frame = frame
    state.operation = operation
    state.phase = "pending" if operation == "clarify" else "selected"
    state.pending_question = draft.clarify_question or None
    state.input["base"] = public_frame(base) if base else None
    state.input["operation"] = operation
    state.input["basis"] = frame.basis
    started = perf_counter()
    source_texts = [
        current_message,
        *[m["content"] for m in state.input.get("history", []) if m["role"] == "user"],
    ]
    names = list(dict.fromkeys(draft.project_mentions))
    if any(
        not name or len(name) > 64 or not any(name in text for text in source_texts)
        for name in names
    ):
        raise TaskStateError("项目名称候选缺少用户消息来源")
    # 从原文精确匹配范围内名称，补足模型漏提；候选仅供消歧，不自动添加筛选。
    predicates = [
        Project.workspace_id == run.workspace_id,
        Project.name != "",
        func.instr(current_message, Project.name) > 0,
    ]
    if run.project_id is not None:
        predicates.append(Project.id == run.project_id)
    literal_names = (
        (
            await db.execute(
                select(Project.name).where(*predicates).distinct().order_by(Project.name).limit(6)
            )
        )
        .scalars()
        .all()
    )
    names = list(dict.fromkeys([*literal_names, *names]))
    if len(names) > 5:
        raise TaskStateError("本轮涉及的项目超过候选上限，请明确需要统计的项目")
    matches = []
    for name in names:
        predicates = [Project.workspace_id == run.workspace_id, Project.name == name]
        if run.project_id is not None:
            predicates.append(Project.id == run.project_id)
        projects = (await db.execute(select(Project).where(*predicates).limit(2))).scalars().all()
        matches.append(
            {
                "name": name,
                "status": "unique"
                if len(projects) == 1
                else "ambiguous"
                if projects
                else "unknown",
            }
        )
    state.input["projects"] = matches
    initial_history = len(state.input.get("history", []))
    initial_tasks = len(state.input.get("tasks", []))
    # 当前消息和选定基线加入后仍须满足预算，优先删除未选任务和较早历史。
    while (
        len(json.dumps(state.input, ensure_ascii=False).encode())
        > get_settings().knowledge_agent_task_context_bytes
    ):
        if state.input.get("tasks"):
            state.input["tasks"].pop()
        elif state.input.get("history"):
            state.input["history"].pop(0)
        else:
            raise TaskStateError("本轮任务上下文超过预算，请缩短请求或明确筛选条件")
    state.metadata_audit = {
        **state.metadata_audit,
        "names": names,
        "literal_names": list(literal_names),
        "matches": matches,
        "duration_ms": int((perf_counter() - started) * 1000),
        "selected_trimmed_history": initial_history - len(state.input.get("history", [])),
        "selected_trimmed_tasks": initial_tasks - len(state.input.get("tasks", [])),
    }
    references = []
    if draft.result_position is not None:
        if not base or not base.result_run_id:
            raise TaskStateError("所选任务没有可引用的展示列表")
        result_run = await db.get(KnowledgeAgentRun, base.result_run_id)
        if not result_run or (
            result_run.workspace_id,
            result_run.owner_user_id,
            result_run.conversation_id,
            result_run.scope_type,
            result_run.project_id,
        ) != (
            run.workspace_id,
            run.owner_user_id,
            run.conversation_id,
            run.scope_type,
            run.project_id,
        ):
            raise TaskStateError("所选列表不属于当前任务范围")
        if result_run.status not in {"completed", "partial"} or not (
            state.epoch <= result_run.user_message_id < run.user_message_id
        ):
            raise TaskStateError("所选列表尚未完成或已经越过当前对话边界")
        items = json.loads(result_run.entry_result_json or "{}").get("items", [])
        if draft.result_position > len(items):
            raise TaskStateError("最近的展示列表中没有这个序号，请重新选择")
        references = [items[draft.result_position - 1]["entry_id"]]
    write_state(run, state)
    return state, references


def source_for(state: TaskState, run, source: str, quote: str) -> dict:
    if source == "current":
        text, message_id = state.input.get("current_message", ""), run.user_message_id
    else:
        item = next(
            (
                m
                for m in state.input.get("history", [])
                if m.get("handle") == source and m["role"] == "user"
            ),
            None,
        )
        text, message_id = (item["content"], int(source[1:])) if item else ("", None)
    if not quote or quote not in text or message_id is None:
        raise TaskStateError("条件变化没有合法的用户原文依据")
    return {"message_id": message_id, "quote": quote, "origin": "explicit"}


def merge_query_delta(run, delta: QueryTaskDeltaDraft):
    state = read_state(run)
    if not state or not state.frame:
        raise TaskStateError("查询缺少选定任务")
    if delta.clarify_question:
        state.pending_question = delta.clarify_question
        state.phase = "pending"
        write_state(run, state)
        return None
    baseline = state.frame.plan or {"entry_set": {}, "outputs": []}
    entry_set = dict(baseline["entry_set"])
    seen = set()
    for change in delta.changes:
        if change.field in seen:
            raise TaskStateError("同一条件不能同时执行多个变更")
        seen.add(change.field)
        source = source_for(state, run, change.source, change.quote)
        value = (
            change.value.model_dump(mode="json", by_alias=True)
            if isinstance(change.value, BaseModel)
            else change.value
        )
        if change.operation == "clear":
            if value is not None:
                raise TaskStateError("撤销条件不能同时提供新值")
            entry_set.pop(change.field, None)
        else:
            if value is None:
                raise TaskStateError("设置条件需要明确值")
            entry_set[change.field] = value
        state.frame.sources[change.field] = {
            **source,
            "origin": change.source_kind,
            "operation": change.operation,
        }
        if change.field == "project_name":
            state.frame.binding = None
    outputs = baseline["outputs"]
    if delta.outputs is not None:
        source = source_for(state, run, delta.output_source, delta.output_quote)
        state.frame.sources["outputs"] = source
        outputs = [o.model_dump(mode="json", by_alias=True) for o in delta.outputs]
    plan = normalize_structured_query_plan({"entry_set": entry_set, "outputs": outputs})
    plan.prompt_version = "task-v1"
    state.frame.plan = plan.model_dump(mode="json", by_alias=True)
    state.changes = delta.model_dump(mode="json", by_alias=True)
    state.phase = "planned"
    write_state(run, state)
    return plan


async def verify_task_project(db, run, plan) -> None:
    state = read_state(run)
    if not state or not state.frame:
        return
    name = plan.entry_set.project_name
    if not name:
        state.frame.binding = None
    else:
        predicates = [Project.workspace_id == run.workspace_id, Project.name == name]
        if run.project_id is not None:
            predicates.append(Project.id == run.project_id)
        matches = (await db.execute(select(Project).where(*predicates).limit(2))).scalars().all()
        if len(matches) != 1:
            raise TaskStateError("该项目名称无法唯一确定，请确认项目名称")
        binding = state.frame.binding
        if binding and binding.project_id != matches[0].id:
            raise TaskStateError("原任务项目已经不可用，不能自动替换成同名项目")
        state.frame.binding = ProjectBinding(project_id=matches[0].id, name=matches[0].name)
    write_state(run, state)


async def prepare_composite_task(db, run, plan) -> None:
    """复合回答只有单一结构化集合时保存其实际查询定义，避免继承未执行的基线。"""
    state = read_state(run)
    if not state or not state.frame:
        return
    requests = plan.structured_requests
    if len(requests) == 1:
        actual = requests[0].query_plan
        old_set = (state.frame.plan or {}).get("entry_set", {})
        if old_set.get("project_name") != actual.entry_set.project_name:
            state.frame.binding = None
        state.frame.plan = actual.model_dump(mode="json", by_alias=True)
        state.frame.sources = {
            "composite": {"message_id": run.user_message_id, "origin": "inferred"},
        }
        write_state(run, state)
        await verify_task_project(db, run, actual)
    else:
        state.frame.plan = None
        state.frame.binding = None
        write_state(run, state)


def finalize_task(run, *, usable: bool, clarification: str | None = None) -> None:
    state = read_state(run)
    if not state or not state.frame:
        return
    if clarification:
        state.phase, state.pending_question = "pending", clarification
    elif usable:
        state.phase = "committed"
        state.frame.context_version_id = (
            run.output_context_version_id or state.frame.context_version_id
        )
        snapshot = json.loads(run.entry_result_json or "{}")
        displays_list = snapshot and (
            snapshot.get("schema_version") == "v1"
            or (snapshot.get("output_completeness") or {}).get("entries") is not None
        )
        if displays_list or snapshot.get("items"):
            state.frame.result_run_id = run.id
            state.frame.result_titles = [
                str(item.get("title", ""))[:255] for item in snapshot.get("items", [])[:50]
            ]
        state.pool = [f for f in state.pool if f.handle != state.frame.handle]
        state.pool.append(state.frame)
        while len(state.pool) > 5:
            protected = {state.frame.handle, state.frame.parent}
            remove = next((i for i, f in enumerate(state.pool) if f.handle not in protected), 0)
            state.pool.pop(remove)
    write_state(run, state)


def task_input(run) -> dict | None:
    state = read_state(run)
    return state.input if state and state.phase != "waiting" else None


def task_basis_text(run) -> str:
    state = read_state(run)
    if not state or not state.frame:
        return ""
    return {
        "auto": "",
        "no_grove": "不查我的知识库，只用通用知识",
        "knowledge_only": "只根据我的知识库回答",
    }[state.frame.basis]
