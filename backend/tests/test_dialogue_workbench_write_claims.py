"""193809 会话：候选稿否定范围及无工具收尾的确定性回归。"""

import pytest
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from app.db.session import async_session_factory
from app.models import Entry
from evals.dialogue_loop import loop
from evals.dialogue_loop.core import DialogueAnswer
from evals.dialogue_loop.instrumentation import BudgetedModel
from tests.test_dialogue_workbench_continuity import output, pin_seeded_entry
from tests.test_knowledge_agent_dialogue_loop import _state

WRITE_ERROR = "候选修改稿不得声称已经写入或修改正式记录"
# 保留现场导致误判的开头、结尾；正文使用测试材料，避免依赖私人会话文件。
DRAFT = (
    "以下属于基于当前条目与其所引来源的分析性补充，"
    "不是官方标准原文核验结果，也没有写入正式条目。\n"
    "原记录概括 ENF 等级。建议补充适用范围和检测条件，具体数值待核验。\n"
    "上述补充稿为候选内容，不代表已核验或已写入正式条目。"
)


@pytest.mark.parametrize("statement", [
    "尚未写入正式记录。",
    "没有写入正式记录。",
    "并非已写入正式记录。",
    "不代表已核验或已写入正式条目。",
    "不代表已经核验或者已经写入正式条目。",
    "不意味着已验证及已更新正式记录。",
    "不是已保存或已修改正式记录。",
    "不代表已核验、已保存以及已写入正式记录。",
    "不代表 已核验 或 已写入正式记录。",
    "不代表已写入。不代表已写入。",
])
def test_negated_statuses_pass_shared_candidate_validation(statement):
    state = _state()
    state.editing_active = True
    state.editing_purpose = "candidate"
    answer = DialogueAnswer.model_validate({"blocks": [{
        "kind": "text", "text": DRAFT + "\n" + statement,
    }]})
    assert loop.output_errors(answer, state) == []


@pytest.mark.parametrize("statement", [
    "已写入正式记录。",
    "已经写入正式记录。",
    "已保存正式记录。",
    "已经保存正式记录。",
    "已更新正式记录。",
    "已经更新了正式记录。",
    "已修改正式记录。",
    "已经修改正式记录。",
    "更新好了。",
    "写入完成。",
    "不代表已写入，但我已写入正式记录。",
    "不代表已写入。我已写入正式记录。",
    "不代表已写入\n已写入正式记录。",
    "不代表已核验，已写入正式记录。",
    "不代表已核验或我已写入正式记录。",
    "不代表已核验或已写入正式记录，但我已经更新了正式记录。",
    "原稿未写入，但我已经更新了正式记录。",
    "不管怎样已写入正式记录。",
    "不是只有已写入正式记录这一项。",
    "并非不代表已写入正式记录。",
])
def test_negation_cannot_hide_any_positive_claim(statement):
    state = _state()
    state.editing_active = True
    state.editing_purpose = "candidate"
    answer = DialogueAnswer.model_validate({"blocks": [
        {"kind": "text", "text": DRAFT},
        {"kind": "text", "text": statement},
    ]})
    assert WRITE_ERROR in loop.output_errors(answer, state)


@pytest.mark.asyncio
@pytest.mark.parametrize("resume_saved_draft", [False, True])
async def test_observed_candidate_finalizes_and_saved_draft_resumes_without_reading(
    resume_saved_draft,
):
    state = _state()
    state.instrumentation.context_policy_enabled = True
    seeded = await pin_seeded_entry(state)
    message = "按你推荐的，把内容补充一下，发给我"
    state.current_message = message
    if resume_saved_draft:
        # 模拟升级前已因否定声明被拒绝、保存了完整候选稿的会话。
        await loop.select_editing_context(state, "edit", purpose="candidate")
        draft = DialogueAnswer.model_validate({"blocks": [{"kind": "text", "text": DRAFT}]})
        state.candidate_draft = draft.model_dump()
        loop.preserve_editing_draft(state, draft)
        state.candidate_draft_errors = [WRITE_ERROR]
        state.instrumentation.finalize_status = "invalid_output"
        assert await loop._attach_finalize_continuation(state, message, [])
        state.begin_turn(5, "继续")
        message = "继续"
    calls = []

    def respond(messages, info):
        calls.append(info)
        if not resume_saved_draft and len(calls) == 1:
            return ModelResponse(parts=[ToolCallPart("editing_context", {
                "action": "edit", "purpose": "candidate",
            })])
        assert not info.function_tools
        if resume_saved_draft:
            assert any(
                DRAFT in getattr(part, "content", "")
                for message in messages for part in message.parts
                if isinstance(getattr(part, "content", None), str)
            )
        return output(info, [{"kind": "text", "text": DRAFT}])

    model = BudgetedModel(FunctionModel(respond), state.instrumentation, "dialogue_agent")
    turn, _ = await loop.run_turn(loop.build_agent(model), state, message, [])
    assert turn["status"] == "completed", turn
    assert state.editing_context.draft["blocks"][0]["text"] == DRAFT
    assert state.continuation is None
    if resume_saved_draft:
        assert turn["context"]["continuation_mode"] == "finalize_only"
        assert turn["tool_calls"] == []
        assert len(calls) == 1
    else:
        assert [event["tool"] for event in turn["tool_calls"]] == ["editing_context"]
        assert len(calls) == 2
    async with async_session_factory() as db:
        entry = await db.get(Entry, seeded["entry_id"])
        assert entry.content == seeded["content"]


@pytest.mark.asyncio
async def test_finalizer_still_rejects_later_positive_write_claim():
    state = _state()
    state.instrumentation.context_policy_enabled = True
    seeded = await pin_seeded_entry(state)
    state.current_message = "按推荐补充一下，发给我"
    calls = []

    def respond(messages, info):
        calls.append(info)
        if len(calls) == 1:
            return ModelResponse(parts=[ToolCallPart("editing_context", {
                "action": "edit", "purpose": "candidate",
            })])
        assert not info.function_tools
        return output(info, [{"kind": "text", "text": DRAFT + "\n我已写入正式条目。"}])

    model = BudgetedModel(FunctionModel(respond), state.instrumentation, "dialogue_agent")
    turn, _ = await loop.run_turn(loop.build_agent(model), state, state.current_message, [])
    assert turn["status"] == "partial_completed", turn
    assert WRITE_ERROR in str(turn["finalization"])
    assert state.continuation is not None
    assert len(calls) == 2
    async with async_session_factory() as db:
        entry = await db.get(Entry, seeded["entry_id"])
        assert entry.content == seeded["content"]
