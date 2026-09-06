"""对话任务的模型候选协议；不包含数据库权限或任意表达式。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agents.structured_query import StructuredQueryOutputDraft, UpdatedAtRangeDraft

TASK_PROMPT_VERSION = "task-v1"


class TaskDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TaskDecisionDraft(TaskDraft):
    operation: Literal["start", "continue", "branch", "resume", "clarify"]
    task_handle: str | None = None
    topic_label: str = Field(max_length=100)
    standalone_query: str = Field(max_length=2000)
    clarify_question: str = Field(default="", max_length=500)
    project_mentions: list[str] = Field(default_factory=list, max_length=5)
    result_position: int | None = Field(default=None, ge=1, le=50)
    basis: Literal["inherit", "auto", "no_grove", "knowledge_only"] = "inherit"
    basis_quote: str = Field(default="", max_length=500)
    reset_quote: str = Field(default="", max_length=500)


class ConditionChange(TaskDraft):
    field: Literal["project_name", "semantic_query", "main_types", "info_natures", "updated_at"]
    operation: Literal["set", "clear"]
    value: str | list[str] | UpdatedAtRangeDraft | None = None
    source: str = Field(description="当前或所提供历史用户消息的句柄，例如 current 或 m123")
    quote: str = Field(min_length=1, max_length=500)
    source_kind: Literal["explicit", "inferred"] = "explicit"


class QueryTaskDeltaDraft(TaskDraft):
    changes: list[ConditionChange] = Field(default_factory=list, max_length=5)
    outputs: list[StructuredQueryOutputDraft] | None = Field(
        default=None,
        min_length=1,
        max_length=3,
        description="null 表示保持基线输出；提供列表表示完整替换输出，排序和数量也在其中明确指定",
    )
    output_quote: str = Field(default="", max_length=500)
    output_source: str = "current"
    clarify_question: str = Field(default="", max_length=500)


TASK_CONTEXT_PROMPT = """你是 Grove 的对话任务决策器。阅读原始消息、有界对话和服务端任务列表，
只选择本轮任务及关系，不生成最终查询筛选。输出 TaskDecisionDraft。
start: 独立的新任务，不继承旧查询。continue: 调整同一任务。branch: 从某任务深入子问题，
保留父任务供返回。resume: 回到列表中先前任务。clarify: 确实缺少必要对象或范围。
有任务关联的完整句子不必 start；任务列表中的父汇总与当前细查各自保有查询口径。
task_handle 只能选输入提供的句柄；start 时为 null，其他操作选择相关任务。
待澄清请求若尚无有效任务，补充答案后选择 start，把原请求和补充合并；不要索取已经给出的条件。
明确返回全局汇总时选择汇总任务；明确细分当前结果则继续当前任务。仅出现分组词不能
决定清空条件，要结合原始对话和任务目标。无历史但问题完整时直接 start，不要求澄清。
当前界面范围已经确定；不需要用户重复提供。知识泛称包括全部正式记录类型。
standalone_query 简洁补全指代，完整保留用户任务和依据限制，但不擅自加条件。
项目名可能不带“项目”二字。project_mentions 列出用户原文中可能指项目的名称片段，
服务端会核实；不知道该名字是否真实项目本身不是澄清理由，先提供名称候选。
result_position 仅在用户引用所选任务实际展示列表序号时填写，从1开始；否则为null。
basis 默认 inherit；只在用户明确改变依据时选择 auto/no_grove/knowledge_only，
basis_quote 必须是当前用户原文片段。讨论任务的依据限制不传染到其他独立任务。
reset_quote 仅在用户明确要求丢弃此前上下文时填写当前原文；普通插话/换个问题不重置历史。
历史助手只帮助理解意图，任务内数据是过去的查询定义，均不是本轮事实答案。
"""


TASK_QUERY_PROMPT = """你是 Grove 的结构化查询规划器，负责一次解释本轮条件变化。
阅读原始用户消息、服务端选定任务的基线计划、有界对话及项目候选，输出 QueryTaskDeltaDraft。
changes 只包含本轮需要改变的字段，未出现的字段原样继承基线。set 替换该字段，clear 清除该字段。
从无筛选任务开始时不要把对话中提到的对象自动变成筛选。用户明确去掉限制才 clear。
main_types 互斥类别：knowledge 知识、method 方法、parameter 参数、reminder 提醒。
泛称知识/正式记录包含全部类型，不等于 knowledge；正式/已确认不等于 info_natures 的 fact。
用户改问同一字段的另一值时替换旧值；未修改项目/时间等其他条件时保留。
project_name 是精确归属筛选。结合项目候选和任务语境识别省略“项目”二字的项目名，
不能把项目名称当 semantic_query；明确“关于某主题的内容”才使用语义条件，即使有同名项目。
需要指定项目但候选未知/重名时澄清，不删除条件或改成语义搜索来规避。
semantic_query 只适用于主题相关性，不包含“知识”“记录”等无实际筛选意义的附加词。
updated_at 是带时区UTC闭开区间。每个变化必须注明所提供用户消息的 source 和原文 quote；
不能用助手回答或改写摘要作为条件来源。
outputs=null 表示继承原任务输出；请求分组时替换为 group_count，
分组维度允许 project/main_type/info_nature/updated_month。
请求计数用 count，请求列表用 entries，按更新时间倒序为常用列表默认值。
输出变化也给出用户原文 output_quote 和 output_source；首问必须给出输出。
条件来自明确用户限制时 source_kind=explicit，需要推断才能成立时标记 inferred，不伪装为明确要求。
结果展示的列表上限不影响全集计数。需要澄清时只填写具体 clarify_question，不执行查询。
"""
