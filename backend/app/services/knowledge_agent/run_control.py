"""知识 Agent Run 的通用取消控制，不包含任何回答编排职责。"""

from app.models.knowledge_agent import RUN_PROCESSING
from app.services.knowledge_agent.runs import read_run_cancel_state


class RunCancelled(Exception):
    """Run 已被取消：迟到的模型或工具结果不得提交。"""


async def check_run_cancelled(run_id: int) -> None:
    """在独立短会话中读取最新取消状态，并在处理中断执行。"""
    cancel_requested, status = await read_run_cancel_state(run_id)
    if cancel_requested and status == RUN_PROCESSING:
        raise RunCancelled("运行中被取消")
