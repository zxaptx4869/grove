"""知识协作助手的指令交付、无资料回答和原有输出边界。"""

import pytest
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.function import FunctionModel

from app.db.session import async_session_factory
from app.models import Entry
from evals.dialogue_loop import loop
from evals.dialogue_loop.instrumentation import BudgetedModel
from tests.test_dialogue_workbench_continuity import output, pin_seeded_entry
from tests.test_knowledge_agent_dialogue_loop import _state

INTRODUCTION = (
    "我是知林 Grove 的知识助手，可以帮你查找和理解已有知识，"
    "也能和你一起讨论、补充和整理内容。修改会先作为候选稿交给你，由你决定是否采纳。"
)


def assert_role_received(info):
    # 断言实际模型请求，防止只定义角色常量却漏接主 Agent 或收尾路径。
    assert loop.ASSISTANT_ROLE_PROMPT in info.instructions
    assert loop.ANSWER_PROTOCOL_PROMPT in info.instructions
    assert info.output_tools[0].name == "final_result"


@pytest.mark.asyncio
@pytest.mark.parametrize("message", ["你是谁", "你能帮我做什么"])
async def test_identity_answer_delivers_once_without_material_tools(message):
    state = _state()
    state.begin_turn(5, message)
    state.instrumentation.context_policy_enabled = True
    calls = []

    def respond(messages, info):
        assert_role_received(info)
        calls.append(info)
        return output(info, [{"kind": "text", "text": INTRODUCTION}])

    model = BudgetedModel(FunctionModel(respond), state.instrumentation, "dialogue_agent")
    turn, _ = await loop.run_turn(loop.build_agent(model), state, message, [])
    assert turn["status"] == "completed", turn
    assert turn["answer"] == INTRODUCTION
    assert turn["tool_calls"] == []
    assert not turn["finalization"]["attempted"]
    assert len(calls) == 1
    assert state.read_entry_ids == set()
    assert state.current_evidence == set()


@pytest.mark.asyncio
async def test_finalizer_receives_same_identity_and_has_no_material_tools():
    state = _state()
    state.begin_turn(5, "你是谁")
    state.instrumentation.context_policy_enabled = True
    calls = []

    def respond(messages, info):
        assert_role_received(info)
        assert not info.function_tools
        calls.append(info)
        return output(info, [{"kind": "text", "text": INTRODUCTION}])

    model = BudgetedModel(FunctionModel(respond), state.instrumentation, "dialogue_agent")
    result = await loop._finalize_once(
        loop.build_finalizer_agent(model), state, state.current_message, [], [], "test",
    )
    assert loop.render_answer(result.output, state)[0] == INTRODUCTION
    assert state.instrumentation.finalize_response_received
    assert state.instrumentation.finalize_error is None
    assert len(calls) == 1
    assert state.ledger.active_tool_calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("correct_format", [True, False])
async def test_raw_identity_text_keeps_existing_retry_and_failure_boundary(correct_format):
    state = _state()
    state.begin_turn(5, "你是谁")
    state.instrumentation.context_policy_enabled = True
    calls = []

    def respond(messages, info):
        assert_role_received(info)
        calls.append(info)
        if len(calls) == 2 and correct_format:
            return output(info, [{"kind": "text", "text": INTRODUCTION}])
        # 保留现场非理想输出；提示词变更不等于原始文本能绕过校验。
        return ModelResponse(parts=[TextPart(INTRODUCTION)])

    model = BudgetedModel(FunctionModel(respond), state.instrumentation, "dialogue_agent")
    turn, _ = await loop.run_turn(loop.build_agent(model), state, state.current_message, [])
    assert turn["status"] == ("completed" if correct_format else "failed"), turn
    assert turn["tool_calls"] == []
    assert len(calls) == 2
    if correct_format:
        assert turn["answer"] == INTRODUCTION
    else:
        assert "Exceeded maximum output retries" in turn["error"]
        assert not turn["completion"]["can_continue"]


@pytest.mark.asyncio
@pytest.mark.parametrize("finalize", [True, False])
async def test_candidate_prose_with_boundaries_needs_no_fixed_sections(finalize):
    state = _state()
    state.instrumentation.context_policy_enabled = True
    seeded = await pin_seeded_entry(state)
    state.current_message = "帮我把第一条的知识补充一下，发给我"
    await loop.select_editing_context(state, "edit", purpose="candidate")
    prose = (
        "ENF 是现有内容介绍的甲醛释放限量等级。建议补充适用范围和检测条件，"
        "具体数值仍需核对标准。此候选稿尚未写入，新增判断不属于来源原文。"
    )
    calls = []

    def respond(messages, info):
        assert_role_received(info)
        calls.append(info)
        if finalize:
            assert not info.function_tools
        return output(info, [{"kind": "text", "text": prose}])

    model = BudgetedModel(FunctionModel(respond), state.instrumentation, "dialogue_agent")
    if finalize:
        result = await loop._finalize_once(
            loop.build_finalizer_agent(model), state, state.current_message, [], [], "test",
        )
        assert loop.render_answer(result.output, state)[0] == prose
    else:
        turn, _ = await loop.run_turn(loop.build_agent(model), state, state.current_message, [])
        assert turn["status"] == "completed", turn
        assert turn["answer"] == prose
        assert turn["tool_calls"] == []
    assert len(calls) == 1
    assert state.editing_context.draft["blocks"][0]["text"] == prose
    async with async_session_factory() as db:
        entry = await db.get(Entry, seeded["entry_id"])
        assert entry.content == seeded["content"]
