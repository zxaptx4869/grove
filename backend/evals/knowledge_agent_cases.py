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
    requires_previous_answer: bool = False
    review: bool = False
    accepted_statuses: tuple[str, ...] = ("completed",)
    required_tools: tuple[str, ...] = ()
    forbidden_tools: tuple[str, ...] = ()
    target_entry_id: int | None = None
    only_if_continuation: bool = False
    semantic_criteria: tuple[str, ...] = ()


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
                Turn(
                    "把刚才的方法压缩成三个步骤，仍然不用查知识库。",
                    "discussion",
                    requires_previous_answer=True,
                    review=True,
                ),
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
                    "它适合什么样的任务？仍然只用通用知识，不查知识库。",
                    "discussion",
                    requires_previous_answer=True,
                    review=True,
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


def build_task_cases(project_name: str, other_name: str) -> list[Case]:
    """任务状态对照集；首次真实执行前固定，保留集不用于调提示词。"""
    return [
        Case(
            "task_original",
            "用户五轮原话",
            (
                Turn("全部项目我一共有多少个知识"),
                Turn(f"其中{project_name}项目有多少个呢", oracle_scope="project"),
                Turn("按项目统计数量给我", "group", group_by="project"),
                Turn(f"帮我统计{other_name}有多少条知识", oracle_scope="other"),
                Turn("分项目统计数量", "group", group_by="project"),
            ),
            category="任务状态 / 用户反馈",
            notes=["分项目两轮预期按用户反馈为全部项目；不自动接受澄清为通过。"],
        ),
        Case(
            "task_restore",
            "深入后恢复汇总",
            (
                Turn("统计全部项目的知识总数"),
                Turn(f"其中{project_name}有多少条", oracle_scope="project"),
                Turn("回到刚才全部项目的统计，分别列出各项目的数量", "group", group_by="project"),
            ),
            category="任务状态 / 调试",
        ),
        Case(
            "task_replace_clear",
            "替换与撤销条件",
            (
                Turn(
                    f"统计{project_name}项目的方法类型记录数量",
                    main_types=("method",),
                    oracle_scope="project",
                ),
                Turn("类型换成参数，其他不变", main_types=("parameter",), oracle_scope="project"),
                Turn("取消类型限制，统计这个项目全部类型", oracle_scope="project"),
                Turn("再取消项目限制，统计整个工作区的总数"),
            ),
            category="任务状态 / 调试",
        ),
        Case(
            "task_interrupt",
            "通用讨论插话后恢复",
            (
                Turn(
                    f"统计{project_name}项目的方法类型记录数量",
                    main_types=("method",),
                    oracle_scope="project",
                ),
                Turn(
                    "插个问题：只用通用知识简单解释什么是番茄工作法，不查知识库",
                    "discussion",
                    review=True,
                ),
                Turn(
                    "回到插话前的方法数量统计，按信息性质分组",
                    "group",
                    main_types=("method",),
                    group_by="info_nature",
                    oracle_scope="project",
                ),
            ),
            category="任务状态 / 调试",
        ),
        Case(
            "task_project_keep",
            "更换项目后保留集合分组",
            (
                Turn(f"统计{project_name}有多少条知识", oracle_scope="project"),
                Turn(f"换成{other_name}，仍然只统计这个项目", oracle_scope="other"),
                Turn(
                    "这个项目内按类型分别统计", "group", group_by="main_type", oracle_scope="other"
                ),
            ),
            category="任务状态 / 保留集",
        ),
        Case(
            "task_heldout_reset",
            "自然表达解除条件与重置",
            (
                Turn(
                    f"{project_name}里提醒类型的记录有几条",
                    main_types=("reminder",),
                    oracle_scope="project",
                ),
                Turn("别限定提醒了，其他类型也一起算进去", oracle_scope="project"),
                Turn("重新开始：整个工作区有多少条正式记录", context_mode="new_topic"),
            ),
            category="任务状态 / 保留集",
        ),
    ]


def build_core_baseline_cases(targets: list[dict]) -> list[Case]:
    """构造轻量真实基线；目标来自运行前只读快照，不硬编码 Entry ID。"""
    if len(targets) < 2:
        raise ValueError("核心基线需要当前项目至少两条可追溯的正式 Entry")

    data_tools = ("search_knowledge", "query_entries", "read_entries")

    def collaboration_case(target: dict, variant: str) -> Case:
        if variant == "a":
            discuss = (
                "抛开知识库，只把你刚才展示的第一条正文当作讨论对象，"
                "用通用知识分析其中的建议是否合理，说明不确定之处。不要再查知识库。"
            )
            candidate = "按你刚才的分析，为第一条整理一版候选内容，不要写入正式记录。"
            tone = "只调整上一版候选的语气，让它更自然口语化，保留全部内容、限定和不确定性。"
        else:
            discuss = (
                "不要再检索，就你刚展示的第一条正文本身，从通用知识角度"
                "评价它是否可靠，把原文事实和你的建议分开。"
            )
            candidate = "基于上面的评价，给这条记录准备一份候选稿，明确它还没写入正式 Entry。"
            tone = "内容不变，只把刚才的候选稿换成更简短、自然的说法。"
        return Case(
            f"collaboration_{variant}",
            f"完整协作链变体 {variant.upper()}",
            (
                Turn(
                    f"查找与《{target['title']}》相关的正式记录，列出直接相关项。",
                    "search",
                    target_entry_id=target["id"],
                    review=True,
                    semantic_criteria=("检索结果围绕用户指定主题，不把未筛选候选当直接相关",),
                ),
                Turn(
                    "把第一条的正文和来源依据展示出来。",
                    "read_reference",
                    reference_previous=True,
                    required_tools=("read_entries",),
                    forbidden_tools=("search_knowledge", "query_entries"),
                    review=True,
                    semantic_criteria=("“第一条”指向上轮实际展示的首个对象", "正文和来源边界清楚"),
                ),
                Turn(
                    discuss,
                    "anchored_discussion",
                    requires_previous_answer=True,
                    forbidden_tools=data_tools,
                    review=True,
                    semantic_criteria=(
                        "以刚展示正文为讨论对象，不要求用户重贴",
                        "不新增检索，不冒充来源核验",
                        "分析具体且保留合理不确定性",
                    ),
                ),
                Turn(
                    candidate,
                    "candidate",
                    requires_previous_answer=True,
                    accepted_statuses=("completed", "partial"),
                    forbidden_tools=data_tools,
                    review=True,
                    semantic_criteria=(
                        "候选承接前一轮分析，不只重排原 Entry",
                        "自然区分原记录、模型建议与未写入状态",
                    ),
                ),
                Turn(
                    tone,
                    "tone_revision",
                    requires_previous_answer=True,
                    accepted_statuses=("completed", "partial"),
                    forbidden_tools=data_tools,
                    review=True,
                    semantic_criteria=(
                        "保留上一版候选的全部内容而不是回到原 Entry",
                        "保留数量、单位、限定和不确定性",
                        "仍明确未写入正式记录",
                    ),
                ),
                Turn(
                    "继续",
                    "continuation",
                    only_if_continuation=True,
                    accepted_statuses=("completed", "partial"),
                    forbidden_tools=data_tools,
                    review=True,
                    semantic_criteria=(
                        "解决上轮的实际缺口，不重放旧稿",
                        "不重复成功的检索或读取",
                    ),
                ),
                Turn(
                    "现在换个独立问题：我当前可访问几个项目？",
                    "projects",
                    required_tools=("list_projects",),
                    forbidden_tools=data_tools,
                ),
            ),
            scope="project",
            category="核心协作链 / 语义必审",
            notes=[f"运行前动态目标 Entry={target['id']}，项目={target['project_name']}"],
        )

    first, second = targets[:2]
    return [
        Case(
            "retained_read",
            "项目枚举、检索与跨轮读取保留集",
            (
                Turn("我当前可访问哪些项目？", "projects", required_tools=("list_projects",)),
                Turn(
                    f"在当前 Workspace 查找与《{first['title']}》相关的正式记录，按相关性列出。",
                    "search",
                    target_entry_id=first["id"],
                ),
                Turn(
                    "直接读取上一轮第一条的完整正文和来源，不要重新搜索。",
                    "read_reference",
                    reference_previous=True,
                    required_tools=("read_entries",),
                    forbidden_tools=("search_knowledge", "query_entries"),
                    review=True,
                    semantic_criteria=("跨轮直接读取上轮首个对象，无重复搜索",),
                ),
            ),
            category="已有成功能保留集",
        ),
        collaboration_case(first, "a"),
        collaboration_case(second, "b"),
        Case(
            "scope_switch",
            "Workspace 与项目范围切换",
            (
                Turn("当前 Workspace 共有多少条正式记录？", "count"),
                Turn(
                    "范围已切到当前项目，请只统计这个项目的全部正式记录。",
                    "count",
                    change_scope="project",
                ),
            ),
            category="范围切换保留集",
        ),
    ]
