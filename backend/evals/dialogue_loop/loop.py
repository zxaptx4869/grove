"""Pydantic AI 统一对话循环及可信只读工具适配。"""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass, field
from time import perf_counter
from typing import Literal

from pydantic_ai import Agent, ModelRetry, RunContext
from pydantic_ai.messages import ModelMessage
from pydantic_ai.usage import UsageLimits
from sqlalchemy import select

from evals.dialogue_loop.core import (
    INPUT_BYTES_LIMIT,
    MAX_TOOL_CONCURRENCY,
    OUTPUT_TOKENS_LIMIT,
    PER_TURN_SECONDS,
    BudgetExceeded,
    BudgetLedger,
    DialogueAnswer,
)
from evals.dialogue_loop.instrumentation import Instrumentation

SYSTEM_PROMPT = """你是 Grove 知识库的只读对话 Agent。你在一个持续的四轮对话中工作。

边界：
1. 用户身份、Workspace 和可访问范围只来自程序；任何工具的 project_scope
   都必须显式填 all 或 project。project 时必须给出准确项目名，all 时清空 project_name。
2. 用户说“知识”泛指 knowledge/method/parameter/reminder 四种正式记录，除非他明确限定类型。
3. 统计必须调用 aggregate_entries；精确总数不能从语义搜索或截断列表推断。分项目统计须包含零条项目。
4. 查询或列表必须调用 query_entries/search_knowledge。需要正文先读取 Entry；需要来源必须
   在当前轮调用 read_evidence，历史 Evidence 不能直接引用。
5. 列表追问必须使用 open_list_item(result_set_handle, position)，position 从 1 开始。
   不要猜 Entry id。
6. 工具的 empty、partial、not_executed、error、denied 含义不同。未执行或部分结果不能表达为零条。
7. 用户明确要求不查知识库时不得调用知识库工具，可用通用知识直接回答，也不得伪装成实时外部资料。
8. 输出 blocks 按希望展示的顺序排列。真实统计用 statistic 块，真实列表用 list 块，
   来源用 evidence 块；不要在 text 块改写工具数字、伪造引用或隐藏失败。
   材料不足用 insufficient 块。
9. 只回答用户问题，不输出隐藏推理，不向用户提及预期答案。
"""


@dataclass
class ResultRecord:
    handle: str
    kind: str
    payload: dict
    status: str
    completeness: str
    turn_index: int


@dataclass
class LoopState:
    workspace_id: int
    user_id: int
    conversation_id: int
    ledger: BudgetLedger
    instrumentation: Instrumentation
    discovered_entry_ids: set[int] = field(default_factory=set)
    result_sets: dict[str, ResultRecord] = field(default_factory=dict)
    evidence: dict[str, dict] = field(default_factory=dict)
    current_handles: set[str] = field(default_factory=set)
    current_evidence: set[str] = field(default_factory=set)
    tool_events: list[dict] = field(default_factory=list)
    turn_index: int = 0
    run_id: int = 0
    tools_allowed: bool = True
    _handle_sequence: int = 0

    def begin_turn(self, run_id: int, message: str) -> None:
        self.turn_index += 1
        self.run_id = run_id
        self.current_handles.clear()
        self.current_evidence.clear()
        self.tools_allowed = "不查知识库" not in message
        self.ledger.start_turn()

    def store_result(self, kind: str, payload: dict, status: str, completeness: str) -> str:
        self._handle_sequence += 1
        handle = f"rs-{self.conversation_id}-{self._handle_sequence}"
        self.result_sets[handle] = ResultRecord(
            handle, kind, payload, status, completeness, self.turn_index
        )
        self.current_handles.add(handle)
        return handle


@dataclass
class LoopDeps:
    state: LoopState


def _entry_set(
    project_scope: Literal["all", "project"],
    project_name: str | None,
    semantic_query: str | None,
    main_types: list[Literal["knowledge", "method", "parameter", "reminder"]],
) -> dict:
    if project_scope == "project" and not (project_name or "").strip():
        raise ModelRetry("project_scope=project 时必须填写 project_name")
    if project_scope == "all" and project_name is not None:
        raise ModelRetry("project_scope=all 时必须把 project_name 设为 null")
    return {
        "schema_version": "v1",
        "project_name": project_name.strip() if project_name else None,
        "semantic_query": semantic_query.strip() if semantic_query else None,
        "main_types": main_types,
        "info_natures": [],
        "updated_at": None,
    }


def _public_result(result, handle: str) -> dict:
    return {
        "result_handle": handle,
        "status": result.status,
        "completeness": result.completeness,
        "payload": result.payload,
        "error": result.error,
    }


def output_errors(answer: DialogueAnswer, state: LoopState) -> list[str]:
    """返回句柄边界错误；供一次模型纠正与无模型反例测试共用。"""
    errors = []
    for block in answer.blocks:
        if block.kind in {"statistic", "list"}:
            record = state.result_sets.get(block.result_handle)
            expected = block.kind
            if record is None or block.result_handle not in state.current_handles:
                errors.append(f"{block.result_handle} 不是当前轮结果")
            elif record.kind != expected:
                errors.append(f"{block.result_handle} 不是 {expected} 结果")
        elif block.kind == "evidence" and block.evidence_handle not in state.current_evidence:
            errors.append(f"{block.evidence_handle} 不是当前轮核验 Evidence")
    return errors


def list_position_entry_id(state: LoopState, result_set_handle: str, position: int) -> int:
    """将会话内有序列表位置解析为真实 Entry id。"""
    record = state.result_sets.get(result_set_handle)
    items = record.payload.get("items", []) if record and record.kind == "list" else []
    if record is None or record.kind != "list" or not 1 <= position <= len(items):
        raise ValueError("结果集句柄无效、非列表或位置越界")
    return int(items[position - 1]["entry_id"])


async def _dispatch(ctx: RunContext[LoopDeps], tool_name: str, params: dict, kind: str) -> dict:
    from app.db.session import async_session_factory
    from app.models.knowledge_agent import RESULT_COMPLETENESS_UNKNOWN
    from app.services.knowledge_agent.read_tool_adapters import (
        KNOWLEDGE_AGENT_READ_TOOL_REGISTRY,
    )
    from app.services.knowledge_agent.read_tools import ReadToolBudget, dispatch_read_tool
    from app.services.knowledge_agent.tools import RunToolContext

    state = ctx.deps.state
    await state.ledger.reserve_tool()
    if not state.tools_allowed:
        event = {
            "tool": tool_name,
            "status": "not_executed",
            "completeness": RESULT_COMPLETENESS_UNKNOWN,
            "params": params,
            "error": "用户明确要求本轮不查知识库",
            "duration_ms": 0,
        }
        state.tool_events.append(event)
        return event
    tool_budget = ReadToolBudget(
        max_calls=1, timeout_seconds=PER_TURN_SECONDS, max_result_bytes=32_000
    )

    async def not_cancelled() -> None:
        return None

    started = perf_counter()
    async with async_session_factory() as db:
        tool_ctx = RunToolContext(
            run_id=state.run_id,
            workspace_id=state.workspace_id,
            owner_user_id=state.user_id,
            scope_type="workspace",
            project_id=None,
            project_name=None,
            discovered_entry_ids=state.discovered_entry_ids,
        )
        result = await dispatch_read_tool(
            db,
            tool_ctx,
            tool_name=tool_name,
            tool_version="v1",
            params=params,
            budget=tool_budget,
            cancel_check=not_cancelled,
            registry=KNOWLEDGE_AGENT_READ_TOOL_REGISTRY,
        )
        await db.commit()
    payload = result.payload
    if tool_name == "search_knowledge" and len(payload.get("items", [])) > 10:
        payload = {**payload, "items": payload["items"][:10], "truncated_by_experiment": True}
    handle = state.store_result(kind, payload, result.status, result.completeness)
    event = {
        "tool": tool_name,
        "result_handle": handle,
        "status": result.status,
        "completeness": result.completeness,
        "params": params,
        "error": result.error,
        "duration_ms": int((perf_counter() - started) * 1000),
    }
    state.tool_events.append(event)
    if tool_name == "read_evidence":
        for item in result.payload.get("items", []):
            evidence_handle = item.get("evidence_handle")
            if evidence_handle and item.get("citable"):
                state.evidence[evidence_handle] = item
                state.current_evidence.add(evidence_handle)
    public = _public_result(result, handle)
    public["payload"] = payload
    return public


def build_agent(model) -> Agent[LoopDeps, DialogueAnswer]:
    agent = Agent(
        model,
        deps_type=LoopDeps,
        output_type=DialogueAnswer,
        system_prompt=SYSTEM_PROMPT,
        retries=1,
        model_settings={"temperature": 0, "max_tokens": OUTPUT_TOKENS_LIMIT},
        max_concurrency=MAX_TOOL_CONCURRENCY,
        tool_timeout=PER_TURN_SECONDS,
    )

    @agent.tool
    async def list_projects(ctx: RunContext[LoopDeps]) -> dict:
        """列出当前认证 Workspace 中可访问的项目；统计分桶仍应调用 aggregate_entries。"""
        from app.db.session import async_session_factory
        from app.models import Project
        from app.services.knowledge_agent.observability import (
            next_tool_sequence,
            record_tool_call,
        )

        state = ctx.deps.state
        await state.ledger.reserve_tool()
        if not state.tools_allowed:
            event = {
                "tool": "list_projects",
                "status": "not_executed",
                "error": "用户明确要求本轮不查知识库",
            }
            state.tool_events.append(event)
            return event
        async with async_session_factory() as db:
            rows = (
                await db.execute(
                    select(Project.id, Project.name, Project.status)
                    .where(Project.workspace_id == state.workspace_id)
                    .order_by(Project.id)
                )
            ).all()
            await record_tool_call(
                db,
                run_id=state.run_id,
                sequence=await next_tool_sequence(db, state.run_id),
                tool_name="list_projects",
                status="completed" if rows else "empty",
                result_summary=json.dumps({"project_count": len(rows)}, ensure_ascii=False),
            )
            await db.commit()
        payload = {"projects": [{"name": row.name, "status": row.status} for row in rows]}
        handle = state.store_result(
            "projects", payload, "completed" if rows else "empty", "complete"
        )
        event = {
            "tool": "list_projects",
            "result_handle": handle,
            "status": "completed" if rows else "empty",
            "completeness": "complete",
            "params": {},
            "error": None,
            "duration_ms": 0,
        }
        state.tool_events.append(event)
        return {**event, "payload": payload}

    @agent.tool
    async def aggregate_entries(
        ctx: RunContext[LoopDeps],
        project_scope: Literal["all", "project"],
        project_name: str | None,
        operation: Literal["count", "group_count"],
        group_by: Literal["project", "main_type", "info_nature", "updated_month"] | None,
        main_types: list[Literal["knowledge", "method", "parameter", "reminder"]],
    ) -> dict:
        """对完整确定性 Entry 集合精确计数；项目条件每次必须完整给出。"""
        params = {
            "entry_set": _entry_set(project_scope, project_name, None, main_types),
            "operation": operation,
            "group_by": group_by,
        }
        return await _dispatch(ctx, "aggregate_entries", params, "statistic")

    @agent.tool
    async def query_entries(
        ctx: RunContext[LoopDeps],
        project_scope: Literal["all", "project"],
        project_name: str | None,
        semantic_query: str | None,
        main_types: list[Literal["knowledge", "method", "parameter", "reminder"]],
        limit: int,
        sort_field: Literal["relevance", "updated_at", "created_at"],
        sort_direction: Literal["asc", "desc"],
    ) -> dict:
        """按结构化条件查询列表；semantic_query 非空时结果完整性有限。"""
        params = {
            "entry_set": _entry_set(project_scope, project_name, semantic_query, main_types),
            "limit": min(max(limit, 1), 10),
            "sort": {"field": sort_field, "direction": sort_direction},
        }
        result = await _dispatch(ctx, "query_entries", params, "list")
        ids = [item["entry_id"] for item in result.get("payload", {}).get("items", [])]
        ctx.deps.state.ledger.reserve_entries(ids)
        return result

    @agent.tool
    async def search_knowledge(
        ctx: RunContext[LoopDeps],
        project_scope: Literal["all"],
        project_name: None,
        query: str,
    ) -> dict:
        """在授权 Workspace 全部项目中复用真实混合语义搜索；结果不能用于精确计数。"""
        del project_scope, project_name
        result = await _dispatch(ctx, "search_knowledge", {"query": query}, "list")
        ids = [item["entry_id"] for item in result.get("payload", {}).get("items", [])]
        ctx.deps.state.ledger.reserve_entries(ids)
        return result

    @agent.tool
    async def read_entries(ctx: RunContext[LoopDeps], entry_ids: list[int]) -> dict:
        """读取本会话已由列表或搜索发现的 Entry 正文；任意新 id 会被拒绝。"""
        ctx.deps.state.ledger.reserve_entries(entry_ids)
        return await _dispatch(ctx, "read_entries", {"entry_ids": entry_ids}, "entries")

    @agent.tool
    async def read_evidence(
        ctx: RunContext[LoopDeps], entry_id: int, source_ids: list[int]
    ) -> dict:
        """当前轮重新核验已发现 Entry 的真实 Source 原文并创建 Evidence。"""
        ctx.deps.state.ledger.reserve_evidence(len(source_ids))
        return await _dispatch(
            ctx, "read_evidence", {"entry_id": entry_id, "source_ids": source_ids}, "evidence"
        )

    @agent.tool
    async def open_list_item(
        ctx: RunContext[LoopDeps], result_set_handle: str, position: int
    ) -> dict:
        """按本实验会话中实际展示列表的 1-based 位置重新读取对象。"""
        from app.db.session import async_session_factory
        from app.services.knowledge_agent.tools import (
            RunToolContext,
            read_entries,
            resolve_recent_result_entries,
        )

        state = ctx.deps.state
        await state.ledger.reserve_tool()
        try:
            entry_id = list_position_entry_id(state, result_set_handle, position)
        except ValueError:
            event = {
                "tool": "open_list_item",
                "status": "denied",
                "params": {"result_set_handle": result_set_handle, "position": position},
                "error": "结果集句柄无效、非列表或位置越界",
                "duration_ms": 0,
            }
            state.tool_events.append(event)
            return event
        state.ledger.reserve_entries([entry_id])
        async with async_session_factory() as db:
            tool_ctx = RunToolContext(
                run_id=state.run_id,
                workspace_id=state.workspace_id,
                owner_user_id=state.user_id,
                scope_type="workspace",
                project_id=None,
                project_name=None,
                discovered_entry_ids=state.discovered_entry_ids,
            )
            refreshed = await resolve_recent_result_entries(db, tool_ctx, [entry_id])
            if not refreshed.items:
                event = {
                    "tool": "open_list_item",
                    "status": "error",
                    "params": {"result_set_handle": result_set_handle, "position": position},
                    "error": "对象已删除或移出当前范围",
                    "duration_ms": 0,
                }
                state.tool_events.append(event)
                return event
            output = await read_entries(db, tool_ctx, [entry_id])
            await db.commit()
        payload = output.model_dump(mode="json")
        handle = state.store_result(
            "entries", payload, "completed" if output.items else "error", "limited"
        )
        event = {
            "tool": "open_list_item",
            "result_handle": handle,
            "status": "completed" if output.items else "error",
            "completeness": "limited",
            "params": {"result_set_handle": result_set_handle, "position": position},
            "error": None if output.items else "对象读取失败",
            "duration_ms": 0,
        }
        state.tool_events.append(event)
        return {**event, "payload": payload}

    @agent.output_validator
    async def validate_output(ctx: RunContext[LoopDeps], answer: DialogueAnswer) -> DialogueAnswer:
        errors = output_errors(answer, ctx.deps.state)
        if errors:
            raise ModelRetry("；".join(errors))
        return answer

    return agent


def render_answer(answer: DialogueAnswer, state: LoopState) -> tuple[str, list[dict]]:
    """按模型块顺序以真实工具数据渲染，不接受模型填写数字或原文。"""
    lines: list[str] = []
    rendered: list[dict] = []
    for block in answer.blocks:
        if block.kind in {"text", "insufficient"}:
            text = block.text
            lines.append(text)
            rendered.append({"kind": block.kind, "text": text})
        elif block.kind == "statistic":
            record = state.result_sets[block.result_handle]
            payload = record.payload
            if "value" in payload:
                text = f"{block.label}：{payload['value']}"
            else:
                buckets = payload.get("buckets", [])
                values = "；".join(
                    f"{item.get('label') or item.get('key')}：{item.get('count')}"
                    for item in buckets
                )
                text = f"{block.label}：{values or '无分组记录'}"
            lines.append(text)
            rendered.append(
                {
                    "kind": "statistic",
                    "handle": block.result_handle,
                    "text": text,
                    "status": record.status,
                    "completeness": record.completeness,
                }
            )
        elif block.kind == "list":
            record = state.result_sets[block.result_handle]
            lines.append(block.label)
            items = record.payload.get("items", [])
            for index, item in enumerate(items, 1):
                lines.append(
                    f"{index}. {item.get('title', '未命名')}"
                    f"（{item.get('project_name', '未知项目')}）"
                )
            rendered.append(
                {
                    "kind": "list",
                    "handle": block.result_handle,
                    "label": block.label,
                    "items": items,
                    "status": record.status,
                    "completeness": record.completeness,
                }
            )
        else:
            item = state.evidence[block.evidence_handle]
            text = f"来源《{item.get('source_title', '')}》：{item.get('quote', '')}"
            if block.note:
                text = f"{block.note}\n{text}"
            lines.append(text)
            rendered.append(
                {
                    "kind": "evidence",
                    "handle": block.evidence_handle,
                    "text": text,
                    "entry_id": item.get("entry_id"),
                    "source_id": item.get("source_id"),
                }
            )
    return "\n".join(lines), rendered


async def run_turn(
    agent: Agent[LoopDeps, DialogueAnswer],
    state: LoopState,
    message: str,
    history: list[ModelMessage],
) -> tuple[dict, list[ModelMessage]]:
    """执行一轮；超限、模型失败和 usage 缺失均显式保留。"""
    public_history = json.dumps([item for item in history], ensure_ascii=False, default=str)
    if len(public_history.encode("utf-8")) > INPUT_BYTES_LIMIT:
        raise BudgetExceeded("对话上下文超过冻结输入长度，未静默裁剪")
    before_logs = len(state.instrumentation.logs)
    before_events = len(state.tool_events)
    started = perf_counter()
    try:
        async with asyncio.timeout(PER_TURN_SECONDS):
            result = await agent.run(
                message,
                deps=LoopDeps(state),
                message_history=history,
                usage_limits=UsageLimits(
                    request_limit=12,
                    per_request_input_tokens_limit=12_000,
                    output_tokens_limit=24_000,
                    # 输入在派发前另按 48 KiB 硬限制；部分既有模型包装不实现
                    # count_tokens，不能因此把可用的真实配置误判为不可执行。
                    count_tokens_before_request=False,
                ),
            )
        text, blocks = render_answer(result.output, state)
        status = "completed"
        error = None
        new_history = result.all_messages()
        usage = asdict(result.usage) if result.usage is not None else None
    except Exception as exc:
        text = "本轮未完成。"
        blocks = [{"kind": "insufficient", "text": text}]
        status = "failed"
        error = f"{type(exc).__name__}: {exc}"
        new_history = history
        usage = None
    return {
        "message": message,
        "status": status,
        "answer": text,
        "blocks": blocks,
        "error": error,
        "duration_ms": int((perf_counter() - started) * 1000),
        "usage": usage,
        "budget": state.ledger.snapshot(),
        "tool_calls": state.tool_events[before_events:],
        "model_calls": [asdict(item) for item in state.instrumentation.logs[before_logs:]],
    }, new_history
