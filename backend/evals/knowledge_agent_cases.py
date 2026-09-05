"""多轮评测脚本；期望只供评测器使用，不发送给模型。"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Turn:
    message: str
    kind: str = "count"
    main_types: tuple[str, ...] = ()
    group_by: str | None = None
    context_mode: str = "auto"
    change_scope: str | None = None
    oracle_scope: str | None = None
    reference_previous: bool = False
    review: bool = False


@dataclass(frozen=True)
class Case:
    id: str
    title: str
    turns: tuple[Turn, ...]
    scope: str = "workspace"
    category: str = "已有能力衔接"
    notes: list[str] = field(default_factory=list)


ALL_RECORDS = "全部正式记录，包含知识、方法、参数、提醒四种类型，不加其他筛选"


def build_cases(project_name: str, empty_name: str | None) -> list[Case]:
    """项目名来自已认证 Workspace，只替换测试输入，不注入答案。"""
    cases = [
        Case(
            "original",
            "用户原始三轮对话",
            (
                Turn("我账号下，全部项目汇总一共有多少条知识"),
                Turn("分项目汇总给我", "group", group_by="project"),
                Turn("是的，按项目分别统计", "group", group_by="project"),
            ),
            category="真实反馈 / 项目分组能力缺口",
        ),
        Case(
            "paraphrase",
            "同义追问与项目分组",
            (
                Turn(f"当前工作区的{ALL_RECORDS}，总共多少条？"),
                Turn(
                    "这个总数按各个项目拆开给我看看，零条的项目也列出。",
                    "group",
                    group_by="project",
                ),
            ),
            category="泛化 / 项目分组能力缺口",
        ),
        Case(
            "correction",
            "纠正知识一词的统计口径",
            (
                Turn("一共有多少条知识？"),
                Turn(f"我指的是{ALL_RECORDS}，请重新统计总数。"),
            ),
        ),
        Case(
            "type_groups",
            "总数追问类型分组",
            (
                Turn(f"统计当前范围的{ALL_RECORDS}的总数。"),
                Turn("按类型分别统计给我。", "group", group_by="main_type"),
            ),
        ),
        Case(
            "filter_change",
            "项目内替换类型条件",
            (
                Turn(
                    "当前项目中，类型为方法的正式记录有多少条？不加其他筛选。",
                    main_types=("method",),
                ),
                Turn("那提醒类型呢？", main_types=("reminder",)),
            ),
            scope="project",
        ),
        Case(
            "list_reference",
            "排序列表后按序号追问",
            (
                Turn(
                    "列出当前项目最近更新的五条方法类型正式记录，按更新时间倒序。",
                    "list",
                    main_types=("method",),
                ),
                Turn(
                    "第二条详细说说，并给出原文依据。",
                    "reference",
                    reference_previous=True,
                    review=True,
                ),
            ),
            scope="project",
        ),
        Case(
            "discussion",
            "无知识引用的开放讨论连续追问",
            (
                Turn(
                    "只用通用知识，简单解释什么是番茄工作法，不查我的知识库。",
                    "discussion",
                    review=True,
                ),
                Turn("把刚才的方法压缩成三个步骤，仍然不用查知识库。", "discussion", review=True),
            ),
        ),
        Case(
            "new_topic",
            "统计后明确切换话题",
            (
                Turn(
                    "统计当前范围中方法类型正式记录的总数，不加其他筛选。", main_types=("method",)
                ),
                Turn(
                    "换个话题：只用通用知识解释番茄工作法，不查知识库。",
                    "discussion",
                    context_mode="new_topic",
                    review=True,
                ),
                Turn(
                    "它适合什么样的任务？仍然只用通用知识，不查知识库。", "discussion", review=True
                ),
            ),
        ),
        Case(
            "clarification",
            "歧义澄清后补充完整任务",
            (
                Turn("帮我统计那个有多少条。", "clarify"),
                Turn(f"我指的是当前工作区的{ALL_RECORDS}的总数。"),
                Turn("再按类型分别统计。", "group", group_by="main_type"),
            ),
        ),
    ]
    if empty_name:
        cases.extend(
            [
                Case(
                    "empty_project",
                    "空项目统计与继续追问",
                    (
                        Turn(f"当前项目的{ALL_RECORDS}，一共有多少条？"),
                        Turn("方法类型有多少条？", main_types=("method",)),
                    ),
                    scope="empty",
                ),
                Case(
                    "scope_switch",
                    "界面切换项目后不沿用旧范围",
                    (
                        Turn("当前项目方法类型的正式记录总数是多少？", main_types=("method",)),
                        Turn(f"当前项目{ALL_RECORDS}的总数是多少？", change_scope="empty"),
                    ),
                    scope="project",
                ),
                Case(
                    "named_project",
                    "Workspace 内自然语言指定项目",
                    (
                        Turn(
                            f"只统计《{empty_name}》项目的{ALL_RECORDS}，共有多少条？",
                            oracle_scope="empty",
                        ),
                        Turn(
                            f"换成《{project_name}》项目，还是统计全部类型正式记录总数。",
                            oracle_scope="project",
                        ),
                    ),
                    category="自然语言项目解析能力缺口",
                ),
            ]
        )
    return cases
