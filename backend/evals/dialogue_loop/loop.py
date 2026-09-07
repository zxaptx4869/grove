"""Pydantic AI 统一对话循环及可信只读工具适配。"""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass, field, replace
from time import perf_counter
from typing import Literal

from pydantic_ai import Agent, ModelRetry, RunContext
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.usage import UsageLimits
from sqlalchemy import select

from evals.dialogue_loop.core import (
    FINALIZE_SECONDS,
    MAX_TOOL_CONCURRENCY,
    MODEL_INPUT_TOKENS_LIMIT,
    OUTPUT_TOKENS_LIMIT,
    PER_TURN_SECONDS,
    BudgetExceeded,
    BudgetLedger,
    DialogueAnswer,
)
from evals.dialogue_loop.instrumentation import (
    FinalizeRequired,
    Instrumentation,
    estimate_input_tokens,
)

SYSTEM_PROMPT = """你是 Grove 知识库的只读对话 Agent。你在一个持续的四轮对话中工作。

边界：
1. 用户身份、Workspace 和可访问范围只来自程序；任何工具的 project_scope
   都必须显式填 all 或 project。project 时必须给出准确项目名，all 时清空 project_name。
2. 用户说“知识”泛指 knowledge/method/parameter/reminder 四种正式记录，除非他明确限定类型。
3. 精确总数必须调用 count_entries，分组统计必须调用 group_entries；不能从语义搜索、
   截断列表或分类数相加推断用户所问总数。分项目统计须包含零条项目。
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
10. main_types 省略或 null 表示全部正式记录。用户泛称“知识”“知识库记录”时不得默认
    筛成内部 knowledge 类型；只有用户明确限定内部类型时才填写对应值。
""".strip()

NO_KNOWLEDGE_PATTERNS = (
    "不查知识库",
    "不查库",
    "别查知识库",
    "别查库",
    "不用查知识库",
    "不要查知识库",
)


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
    history_turns: list[dict] = field(default_factory=list)
    turn_index: int = 0
    run_id: int = 0
    tools_allowed: bool = True
    _handle_sequence: int = 0

    def begin_turn(self, run_id: int, message: str) -> None:
        self.turn_index += 1
        self.run_id = run_id
        self.current_handles.clear()
        self.current_evidence.clear()
        self.tools_allowed = not any(pattern in message for pattern in NO_KNOWLEDGE_PATTERNS)
        self.ledger.start_turn()
        self.instrumentation.begin_turn()

    def store_result(self, kind: str, payload: dict, status: str, completeness: str) -> str:
        self._handle_sequence += 1
        handle = f"rs-{self.conversation_id}-{self._handle_sequence}"
        self.result_sets[handle] = ResultRecord(
            handle, kind, payload, status, completeness, self.turn_index
        )
        self.current_handles.add(handle)
        return handle

    def remember_turn(self, message: str, answer: str, events: list[dict]) -> None:
        self.history_turns.append(
            {
                "turn": self.turn_index,
                "user": message,
                "answer": answer,
                "tools": [_history_tool_summary(self, event) for event in events],
            }
        )


@dataclass
class LoopDeps:
    state: LoopState


def _entry_set(
    project_scope: Literal["all", "project"],
    project_name: str | None,
    semantic_query: str | None,
    main_types: list[Literal["knowledge", "method", "parameter", "reminder"]] | None,
) -> dict:
    if project_scope == "project" and not (project_name or "").strip():
        raise ModelRetry("字段 project_name：project_scope=project 时必须填写非空项目名")
    if project_scope == "all" and project_name is not None:
        raise ModelRetry("字段 project_name：project_scope=all 时必须设为 null")
    return {
        "schema_version": "v1",
        "project_name": project_name.strip() if project_name else None,
        "semantic_query": semantic_query.strip() if semantic_query else None,
        "main_types": list(main_types or []),
        "info_natures": [],
        "updated_at": None,
    }


def _count_params(
    project_scope: Literal["all", "project"],
    project_name: str | None,
    main_types: list[Literal["knowledge", "method", "parameter", "reminder"]] | None,
) -> dict:
    return {
        "entry_set": _entry_set(project_scope, project_name, None, main_types),
        "operation": "count",
        "group_by": None,
    }


def _group_params(
    project_scope: Literal["all", "project"],
    project_name: str | None,
    group_by: Literal["project", "main_type", "info_nature", "updated_month"],
    main_types: list[Literal["knowledge", "method", "parameter", "reminder"]] | None,
) -> dict:
    return {
        "entry_set": _entry_set(project_scope, project_name, None, main_types),
        "operation": "group_count",
        "group_by": group_by,
    }


def _shorten(text: str | None, limit: int) -> str | None:
    if text is None or len(text) <= limit:
        return text
    return text[:limit] + f"\n[实验材料已缩减；原文保存在程序侧，省略 {len(text) - limit} 字符]"


def _model_payload(kind: str, payload: dict) -> dict:
    """保留本轮推理所需材料，完整正文只留在 result_sets。"""
    if kind == "list":
        items = []
        for item in payload.get("items", []):
            items.append(
                {
                    key: (_shorten(value, 600) if key == "excerpt" else value)
                    for key, value in item.items()
                    if key
                    in {
                        "entry_id",
                        "title",
                        "project_id",
                        "project_name",
                        "main_type",
                        "updated_at",
                        "source_count",
                        "excerpt",
                        "matched_fields",
                        "match_hint",
                    }
                }
            )
        return {**{key: value for key, value in payload.items() if key != "items"}, "items": items}
    if kind == "entries":
        items = []
        for item in payload.get("items", []):
            items.append(
                {
                    **{
                        key: value
                        for key, value in item.items()
                        if key not in {"content", "sources"}
                    },
                    "content": _shorten(item.get("content"), 1_200),
                    "sources": [
                        {
                            key: value
                            for key, value in source.items()
                            if key in {"source_id", "source_title", "attachment_id"}
                        }
                        for source in item.get("sources", [])
                    ],
                }
            )
        return {**payload, "items": items}
    if kind == "evidence":
        items = []
        for item in payload.get("items", []):
            items.append({**item, "quote": _shorten(item.get("quote"), 2_000)})
        return {**payload, "items": items}
    return payload


def _tool_result_summary(payload: dict) -> dict:
    """为实验诊断生成有界摘要，不复制正文或把列表当成精确总数。"""
    summary = {
        key: payload[key]
        for key in ("count", "total", "returned_count", "matched_count")
        if key in payload and isinstance(payload[key], (int, float, str))
    }
    items = payload.get("items")
    if isinstance(items, list):
        summary["returned_items"] = len(items)
        titles = [
            item.get("title")
            for item in items
            if isinstance(item, dict) and item.get("title")
        ]
        if titles:
            summary["titles"] = titles[:5]
    return summary


def _history_tool_summary(state: LoopState, event: dict) -> dict:
    summary = {
        "tool": event.get("tool"),
        "shared_tool": event.get("shared_tool"),
        "conditions": event.get("params", {}),
        "executed_conditions": event.get("shared_params", event.get("params", {})),
        "status": event.get("status"),
        "completeness": event.get("completeness", "unknown"),
        "result_handle": event.get("result_handle"),
        "error": event.get("error"),
    }
    record = state.result_sets.get(event.get("result_handle"))
    if record is None:
        return summary
    payload = record.payload
    if record.kind == "statistic":
        summary["statistics"] = {
            key: payload[key]
            for key in ("value", "group_by", "buckets", "truncated")
            if key in payload
        }
    elif record.kind == "list":
        summary["ordered_items"] = [
            {
                "position": index,
                "entry_id": item.get("entry_id"),
                "title": item.get("title"),
                "project_name": item.get("project_name"),
            }
            for index, item in enumerate(payload.get("items", []), 1)
        ]
    elif record.kind == "entries":
        summary["items"] = [
            {
                "entry_id": item.get("entry_id"),
                "title": item.get("title"),
                "project_name": item.get("project_name"),
                "source_ids": [source.get("source_id") for source in item.get("sources", [])],
            }
            for item in payload.get("items", [])
        ]
    elif record.kind == "evidence":
        summary["sources"] = [
            {
                "entry_id": item.get("entry_id"),
                "source_id": item.get("source_id"),
                "source_title": item.get("source_title"),
                "citable": item.get("citable"),
            }
            for item in payload.get("items", [])
        ]
    return summary


def build_compact_history(state: LoopState) -> list[ModelMessage]:
    """从程序侧记录重建合法、配对且不含历史正文的模型历史。"""
    messages: list[ModelMessage] = []
    for turn in state.history_turns:
        messages.append(ModelRequest(parts=[UserPromptPart(content=turn["user"])]))
        tools = turn["tools"]
        if tools:
            call_parts = []
            return_parts = []
            for index, tool in enumerate(tools, 1):
                call_id = f"history-{turn['turn']}-{index}"
                tool_name = tool.get("tool") or "unknown_tool"
                call_parts.append(
                    ToolCallPart(tool_name, tool.get("conditions", {}), tool_call_id=call_id)
                )
                return_parts.append(
                    ToolReturnPart(tool_name, tool, tool_call_id=call_id)
                )
            messages.append(ModelResponse(parts=call_parts))
            messages.append(ModelRequest(parts=return_parts))
        messages.append(ModelResponse(parts=[TextPart(content=turn["answer"])]))
    return messages


def _without_historical_system_prompts(history: list[ModelMessage]) -> list[ModelMessage]:
    """当前规则由 instructions 注入；历史中的旧 system 不得继续生效。"""
    cleaned: list[ModelMessage] = []
    for message in history:
        if not isinstance(message, ModelRequest):
            cleaned.append(message)
            continue
        parts = [part for part in message.parts if not isinstance(part, SystemPromptPart)]
        if parts:
            cleaned.append(replace(message, parts=parts))
    return cleaned


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


async def _dispatch(
    ctx: RunContext[LoopDeps],
    tool_name: str,
    params: dict,
    kind: str,
    *,
    surface_tool: str | None = None,
    audit_params: dict | None = None,
) -> dict:
    from app.db.session import async_session_factory
    from app.models.knowledge_agent import RESULT_COMPLETENESS_UNKNOWN
    from app.services.knowledge_agent.read_tool_adapters import (
        KNOWLEDGE_AGENT_READ_TOOL_REGISTRY,
    )
    from app.services.knowledge_agent.read_tools import ReadToolBudget, dispatch_read_tool
    from app.services.knowledge_agent.tools import RunToolContext

    state = ctx.deps.state
    state.instrumentation.emit_activity(
        {
            "aggregate_entries": "querying",
            "query_entries": "querying",
            "search_knowledge": "querying",
            "read_entries": "reading_entries",
            "read_evidence": "reading_sources",
        }.get(tool_name, "querying")
    )
    await state.ledger.reserve_tool()
    if not state.tools_allowed:
        event = {
            "tool": surface_tool or tool_name,
            "shared_tool": tool_name,
            "status": "not_executed",
            "completeness": RESULT_COMPLETENESS_UNKNOWN,
            "params": audit_params or params,
            "shared_params": params,
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
        "tool": surface_tool or tool_name,
        "shared_tool": tool_name,
        "result_handle": handle,
        "status": result.status,
        "completeness": result.completeness,
        "params": audit_params or params,
        "shared_params": params,
        "result_summary": _tool_result_summary(payload),
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
    public["payload"] = _model_payload(kind, payload)
    return public


def build_agent(model) -> Agent[LoopDeps, DialogueAnswer]:
    agent = Agent(
        model,
        deps_type=LoopDeps,
        output_type=DialogueAnswer,
        instructions=SYSTEM_PROMPT,
        retries=1,
        model_settings={"temperature": 0, "max_tokens": OUTPUT_TOKENS_LIMIT},
        max_concurrency=MAX_TOOL_CONCURRENCY,
        tool_timeout=PER_TURN_SECONDS,
    )

    @agent.tool
    async def list_projects(ctx: RunContext[LoopDeps]) -> dict:
        """列出当前认证 Workspace 中可访问的项目；统计分桶仍应调用 group_entries。"""
        from app.db.session import async_session_factory
        from app.models import Project
        from app.services.knowledge_agent.observability import (
            next_tool_sequence,
            record_tool_call,
        )

        state = ctx.deps.state
        state.instrumentation.emit_activity("querying")
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
    async def count_entries(
        ctx: RunContext[LoopDeps],
        project_scope: Literal["all", "project"],
        project_name: str | None,
        main_types: list[Literal["knowledge", "method", "parameter", "reminder"]] | None = None,
    ) -> dict:
        """精确统计正式记录总数。main_types 未指定表示全部类型；“知识”泛称不是类型筛选。"""
        params = _count_params(project_scope, project_name, main_types)
        return await _dispatch(
            ctx,
            "aggregate_entries",
            params,
            "statistic",
            surface_tool="count_entries",
            audit_params={
                "project_scope": project_scope,
                "project_name": project_name,
                "main_types": list(main_types or []),
            },
        )

    @agent.tool
    async def group_entries(
        ctx: RunContext[LoopDeps],
        project_scope: Literal["all", "project"],
        project_name: str | None,
        group_by: Literal["project", "main_type", "info_nature", "updated_month"],
        main_types: list[Literal["knowledge", "method", "parameter", "reminder"]] | None = None,
    ) -> dict:
        """按一个明确维度统计正式记录。main_types 未指定表示全部正式类型。"""
        params = _group_params(project_scope, project_name, group_by, main_types)
        return await _dispatch(
            ctx,
            "aggregate_entries",
            params,
            "statistic",
            surface_tool="group_entries",
            audit_params={
                "project_scope": project_scope,
                "project_name": project_name,
                "group_by": group_by,
                "main_types": list(main_types or []),
            },
        )

    @agent.tool
    async def query_entries(
        ctx: RunContext[LoopDeps],
        project_scope: Literal["all", "project"],
        project_name: str | None,
        semantic_query: str | None,
        limit: int,
        sort_field: Literal["relevance", "updated_at", "created_at"],
        sort_direction: Literal["asc", "desc"],
        main_types: list[Literal["knowledge", "method", "parameter", "reminder"]] | None = None,
    ) -> dict:
        """按结构化条件查询列表；semantic_query 非空时结果完整性有限。"""
        params = {
            "entry_set": _entry_set(project_scope, project_name, semantic_query, main_types),
            "limit": min(max(limit, 1), 10),
            "sort": {"field": sort_field, "direction": sort_direction},
        }
        result = await _dispatch(
            ctx,
            "query_entries",
            params,
            "list",
            audit_params={
                "project_scope": project_scope,
                "project_name": project_name,
                "semantic_query": semantic_query,
                "main_types": list(main_types or []),
                "limit": params["limit"],
                "sort": params["sort"],
            },
        )
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
        result = await _dispatch(
            ctx,
            "search_knowledge",
            {"query": query},
            "list",
            audit_params={
                "project_scope": project_scope,
                "project_name": project_name,
                "query": query,
            },
        )
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
        state.instrumentation.emit_activity("reading_entries")
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
            message = "；".join(errors)
            ctx.deps.state.instrumentation.record_validation_failure(
                "reference_validation", message, answer.model_dump(mode="json")
            )
            raise ModelRetry(message)
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
                    "value": payload.get("value"),
                    "group_by": payload.get("group_by"),
                    "buckets": payload.get("buckets", []),
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


def _verified_failure_output(state: LoopState) -> tuple[str, list[dict]]:
    """收尾失败时只展示程序已核验的当前轮结构化结果。"""
    status = state.instrumentation.finalize_status
    notices = {
        "timed_out": "收尾请求超时，本轮未完成。",
        "invalid_output": "收尾输出未通过结构校验，本轮未完成。",
        "not_dispatched": "没有可用请求预算，未派发模型收尾，本轮未完成。",
        "failed": "收尾模型请求失败，本轮未完成。",
        "cancelled": "收尾请求被取消，本轮未完成。",
    }
    notice = notices.get(status, "本轮未完成。")
    lines = [notice]
    blocks: list[dict] = [{"kind": "insufficient", "text": notice}]
    for handle, record in state.result_sets.items():
        if handle not in state.current_handles or record.status not in {"completed", "ok"}:
            continue
        if record.kind == "statistic":
            payload = record.payload
            if "value" in payload:
                text = f"已验证统计：{payload['value']}"
            else:
                values = "；".join(
                    f"{item.get('label') or item.get('key')}：{item.get('count')}"
                    for item in payload.get("buckets", [])
                )
                text = f"已验证分组统计：{values or '无分组记录'}"
            lines.append(text)
            blocks.append(
                {
                    "kind": "statistic",
                    "handle": handle,
                    "text": text,
                    "value": payload.get("value"),
                    "group_by": payload.get("group_by"),
                    "buckets": payload.get("buckets", []),
                    "status": record.status,
                    "completeness": record.completeness,
                }
            )
        elif record.kind == "list":
            items = record.payload.get("items", [])
            lines.append("已验证列表：")
            lines.extend(
                f"{index}. {item.get('title', '未命名')}"
                f"（{item.get('project_name', '未知项目')}）"
                for index, item in enumerate(items, 1)
            )
            blocks.append(
                {
                    "kind": "list",
                    "handle": handle,
                    "label": "已验证列表",
                    "items": items,
                    "status": record.status,
                    "completeness": record.completeness,
                }
            )
    for handle, item in state.evidence.items():
        if handle not in state.current_evidence:
            continue
        text = f"已验证来源《{item.get('source_title', '')}》：{item.get('quote', '')}"
        lines.append(text)
        blocks.append(
            {
                "kind": "evidence",
                "handle": handle,
                "text": text,
                "entry_id": item.get("entry_id"),
                "source_id": item.get("source_id"),
            }
        )
    return "\n".join(lines), blocks


def _usage_limits(request_limit: int) -> UsageLimits:
    return UsageLimits(
        request_limit=request_limit,
        per_request_input_tokens_limit=12_000,
        output_tokens_limit=24_000,
        # 输入在派发前另按确定性估算门禁；部分既有模型包装不实现 count_tokens。
        count_tokens_before_request=False,
    )


def _current_material_history(
    state: LoopState,
    message: str,
    history: list[ModelMessage],
    current_events: list[dict],
) -> list[ModelMessage]:
    """把求解阶段已取得的当前轮材料重建为合法配对消息。"""
    messages = [
        *_without_historical_system_prompts(history),
        ModelRequest(parts=[UserPromptPart(content=message)]),
    ]
    for index, event in enumerate(current_events, 1):
        handle = event.get("result_handle")
        if handle not in state.current_handles and event.get("status") not in {
            "denied",
            "error",
            "not_executed",
        }:
            continue
        tool_name = event.get("tool") or "unknown_tool"
        call_id = f"finalize-{state.turn_index}-{index}"
        content = _history_tool_summary(state, event)
        record = state.result_sets.get(handle)
        if record is not None:
            content["payload"] = _model_payload(record.kind, record.payload)
        messages.append(
            ModelResponse(
                parts=[
                    ToolCallPart(tool_name, event.get("params", {}), tool_call_id=call_id)
                ]
            )
        )
        messages.append(
            ModelRequest(parts=[ToolReturnPart(tool_name, content, tool_call_id=call_id)])
        )
    return messages


async def _finalize_once(
    agent: Agent[LoopDeps, DialogueAnswer],
    state: LoopState,
    message: str,
    history: list[ModelMessage],
    current_events: list[dict],
    reason: str,
) -> object:
    """在独立时间窗内用当前轮已核验材料做唯一一次无工具收尾。"""
    state.instrumentation.begin_finalize(reason)
    before_logs = len(state.instrumentation.logs)
    material_history = _current_material_history(state, message, history, current_events)
    try:
        async with asyncio.timeout(FINALIZE_SECONDS):
            return await agent.run(
                "求解阶段已停止。请只根据本轮已获得并核验的材料收尾。",
                deps=LoopDeps(state),
                message_history=material_history,
                usage_limits=_usage_limits(1),
                retries=0,
            )
    except TimeoutError as exc:
        error = f"{type(exc).__name__}: 收尾超过 {FINALIZE_SECONDS:g} 秒"
        state.instrumentation.finalize_status = "timed_out"
        state.instrumentation.finalize_error = error
        state.instrumentation.finalize_failure = state.instrumentation.describe_failure(
            exc, before_logs
        )
        raise
    except Exception as exc:
        failure = state.instrumentation.describe_failure(exc, before_logs)
        state.instrumentation.finalize_failure = failure
        if state.instrumentation.finalize_response_received:
            state.instrumentation.finalize_status = "invalid_output"
            state.instrumentation.finalize_error = (
                "收尾输出非法，未重试模型请求："
                f"{failure['category']}: {failure['message']}"
            )
        elif state.instrumentation.finalize_error is None:
            state.instrumentation.finalize_status = "failed"
            state.instrumentation.finalize_error = (
                f"{failure['category']}: {failure['message']}"
            )
        raise


async def run_turn(
    agent: Agent[LoopDeps, DialogueAnswer],
    state: LoopState,
    message: str,
    history: list[ModelMessage],
) -> tuple[dict, list[ModelMessage]]:
    """执行一轮；超限、模型失败和 usage 缺失均显式保留。"""
    history = _without_historical_system_prompts(history)
    history_estimate = estimate_input_tokens(history)
    before_logs = len(state.instrumentation.logs)
    before_events = len(state.tool_events)
    started = perf_counter()
    solve_error = None
    solve_failure = None
    error_details = None
    try:
        if history_estimate > MODEL_INPUT_TOKENS_LIMIT:
            raise BudgetExceeded(
                f"压缩后对话上下文输入长度估算 {history_estimate} "
                "超过冻结上限，未派发模型请求"
            )
        async with asyncio.timeout(PER_TURN_SECONDS):
            result = await agent.run(
                message,
                deps=LoopDeps(state),
                message_history=history,
                usage_limits=_usage_limits(12),
            )
    except FinalizeRequired:
        try:
            result = await _finalize_once(
                agent,
                state,
                message,
                history,
                state.tool_events[before_events:],
                state.instrumentation.finalize_reason or "budget_boundary",
            )
        except Exception as finalize_exc:
            text, blocks = _verified_failure_output(state)
            status = "failed"
            error_details = state.instrumentation.finalize_failure
            error = state.instrumentation.finalize_error or (
                f"{type(finalize_exc).__name__}: {finalize_exc}"
            )
            usage = None
        else:
            text, blocks = render_answer(result.output, state)
            state.instrumentation.complete_finalize()
            status = "completed"
            error = None
            usage = asdict(result.usage) if result.usage is not None else None
    except TimeoutError as exc:
        if state.instrumentation.finalize_attempted:
            text, blocks = _verified_failure_output(state)
            status = "failed"
            error_details = state.instrumentation.finalize_failure
            error = state.instrumentation.finalize_error or f"{type(exc).__name__}: {exc}"
            usage = None
        else:
            solve_error = f"{type(exc).__name__}: 求解超过 {PER_TURN_SECONDS:g} 秒"
            solve_failure = state.instrumentation.describe_failure(exc, before_logs)
            try:
                result = await _finalize_once(
                    agent,
                    state,
                    message,
                    history,
                    state.tool_events[before_events:],
                    "solve_timeout",
                )
            except Exception as finalize_exc:
                text, blocks = _verified_failure_output(state)
                status = "failed"
                error_details = state.instrumentation.finalize_failure
                error = state.instrumentation.finalize_error or (
                    f"{type(finalize_exc).__name__}: {finalize_exc}"
                )
                usage = None
            else:
                text, blocks = render_answer(result.output, state)
                state.instrumentation.complete_finalize()
                status = "completed"
                error = None
                usage = asdict(result.usage) if result.usage is not None else None
    except Exception as exc:
        error_details = state.instrumentation.describe_failure(exc, before_logs)
        if state.instrumentation.finalize_reason is not None:
            text, blocks = _verified_failure_output(state)
            error = state.instrumentation.finalize_error or f"{type(exc).__name__}: {exc}"
        else:
            text = "本轮未完成。"
            blocks = [{"kind": "insufficient", "text": text}]
            error = f"{type(exc).__name__}: {exc}"
        status = "failed"
        usage = None
    else:
        text, blocks = render_answer(result.output, state)
        state.instrumentation.complete_finalize()
        status = "completed"
        error = None
        usage = asdict(result.usage) if result.usage is not None else None
    current_events = state.tool_events[before_events:]
    state.remember_turn(message, text, current_events)
    new_history = build_compact_history(state)
    input_estimates = [
        {
            "projected_input_tokens": item.projected_input_tokens,
            "estimated_input_tokens": item.estimated_input_tokens,
            "method": item.input_estimate_method,
            "components": item.estimate_components,
            "request_scope": item.request_scope,
            "actual_input_tokens": item.actual_input_tokens,
            "estimate_ratio": item.estimate_ratio,
            "finalize_only": item.finalize_only,
            "finalize_reason": item.finalize_reason,
        }
        for item in state.instrumentation.logs[before_logs:]
        if item.kind in {"text", "text_not_dispatched"}
    ]
    return {
        "message": message,
        "status": status,
        "answer": text,
        "blocks": blocks,
        "error": error,
        "error_details": error_details,
        "solve_error": solve_error,
        "solve_failure": solve_failure,
        "duration_ms": int((perf_counter() - started) * 1000),
        "usage": usage,
        "budget": state.ledger.snapshot(),
        "tool_calls": current_events,
        "model_calls": [asdict(item) for item in state.instrumentation.logs[before_logs:]],
        "context": {
            "history_estimated_input_tokens": history_estimate,
            "input_estimates": input_estimates,
            "history_turns": len(state.history_turns),
            "solve_seconds_limit": PER_TURN_SECONDS,
            "finalize_seconds_limit": FINALIZE_SECONDS,
        },
        "finalization": state.instrumentation.finalization_snapshot(),
    }, new_history
