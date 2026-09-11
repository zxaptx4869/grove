## Context

第三批已在实验统一循环中建立语义候选分层、单一授权结果集合、位置指代、搜索去重与精确部分完成状态。本 change 只处理长对话和收尾阶段暴露的四个相连缺口。真实失败发生在 `session-20260909-222648 / e49b01d3-db3e-47dd-bfa4-8cfc84160e7a` 第四轮：模型已正确将“第一条”解析为 ENF，但第一次正常请求投影约 9028，未派发便进入 finalize；原 Agent 在唯一收尾请求中实际执行 `read_evidence(7,[66,89])`，随后因 `request_limit=1` 无法组织最终回答，且没有可恢复 continuation。

当前 `build_compact_history` 会压缩工具结果，却把完整 `turn["answer"]` 作为 `TextPart` 写回历史。渲染答案包含 Entry 正文和 Evidence 原文，因而程序侧材料又以长文本进入模型历史。`BudgetedModel` 也把 9000 软阈值应用到本轮第一次请求；收尾只删除 Provider schema 中的 function tools，却复用注册了工具的 Agent。

## Goals / Non-Goals

**Goals:**

- 让模型历史只携带继续对话所需的有界语义和对象映射，正文与来源材料留在程序侧。
- 保持所有预算数值不变，修正第一次请求与后续请求的软阈值触发时机。
- 让 finalizer 在程序级没有资料工具执行能力，并保留一次请求上限。
- 让“材料已经取得、只差最终回答”的失败可以在同一工作台进程内真实续执行。
- 保持第三批授权集合、来源边界、只读与 Workspace 隔离。

**Non-Goals:**

- 不实现分页、全局查询效率优化或输入估算算法重做。
- 不新增摘要、规划、分类或评分模型，不提高上下文、工具、文本或时间预算。
- 不把 continuation 扩展为可跨服务重启恢复的通用任务系统。
- 不接入正式 App/API/Worker，不新增任何 Entry/Source 写权限。

## Decisions

### 1. 历史采用结构化摘要块与分级确定性压缩

`LoopState.remember_turn` 改为接收渲染后的结构化回答块和 completion，而不是完整回答字符串。每轮历史记录包含：用户原话、工具结构摘要、普通文字/不足说明的有界摘要、回答引用元数据和未完成状态。`entry` 与 `evidence` 块只记录 Entry/Source/Attachment ID、句柄、状态与关系，不记录 `content`、`quote` 或渲染 `text`；列表顺序继续由工具摘要和 `result_sets` 保存。

单轮普通回答摘要上限设为 1200 个 Unicode 字符，优先保留首尾以兼顾核心结论、候选性质和后续建议。整体历史使用既有输入估算器控制在 5000 token 目标内：先移除较早轮次的非必要普通回答摘要，只保留用户原话、决定/缺口标记和对象映射；再把较早工具摘要缩为条件、状态、句柄、统计及有序对象/来源关系。这个目标是上下文装配边界，不改变 9000/12000 请求预算。若用户原话与必要映射本身仍使完整请求超过 12000，则拒绝派发并说明硬限制。

不采用对渲染字符串做关键字删除，因为它无法可靠区分模型分析、Entry 正文和 Evidence 原文，也容易删除后续承接信息；不新增摘要模型以避免额外语义漂移和预算。

### 2. 软阈值判断使用本轮正常请求序号

`BudgetedModel` 在 `phase=solve` 时读取本轮已经派发的文本请求数。计数为零时，9000 软阈值不触发 finalize，但完整请求仍经过 12000 硬门禁、文本/批次预算与时间预算；计数大于零时，投影达到 9000 就转入 finalize，不依赖工具是否成功或是否取得材料。保留最后一个文本请求给收尾的既有规则仍然优先生效。

这不是提高预算：9000、12000、单轮 12 次文本、8 次工具、30 个 Entry、20 个 Evidence、120 秒求解、15 秒收尾和批次上限全部保持原值。

### 3. Finalizer 使用单独 Agent 且只注册结构化输出

`build_finalizer_agent` 与普通 `build_agent` 共用同一已包装模型、`DialogueAnswer`、模型设置和引用校验，但不装饰任何资料工具，也不注入普通阶段的动态工具 instructions。`_finalize_once` 只接收该 Agent。Instrumentation 在 finalize 响应中检测除输出工具外的任何 ToolCallPart；一旦发现，立即记录 `finalize_tool_attempted` 并抛出确定性失败，不把响应交给可执行资料工具的运行时，也不追加请求。

只在 Provider 参数层隐藏 schema 仍不足以阻止原 Agent 按模型输出找到已注册工具，因此不再作为隔离手段。独立多模型规划架构不在本次范围内。

### 4. Finalize-only continuation 保存内存材料，公开记录只保存摘要

`ContinuationState` 增加只用于 `finalize_answer` 的原始问题、已解析指代、授权集合快照、已确认 result/evidence 材料副本和材料指纹。材料副本仅存在当前服务进程的 `LoopState`；`snapshot()` 返回工作台可保存的有界元数据和指纹，不返回完整正文或来源原文。浏览器刷新仍通过当前 runtime context 续执行；服务重启后旧对话继续按现有规则只读，不承诺恢复内存材料。

continuation 在收尾失败且存在当前轮可展示材料时建立，唯一 pending step 为 `finalize_answer`。收到明确“继续”时，`run_turn` 在进入普通 Agent 前识别该状态，执行程序侧材料复验，然后直接调用 finalizer。其他消息视为新主题并清理旧 finalize-only continuation，不强制恢复。

复验在隔离数据库中直接查询 WorkspaceMember、Entry、Project、EntrySourceEvidence、Source 与 Attachment，不调用模型资料工具，也不新增工具审计。Entry 标题/正文、来源标题、关联 quote、Attachment 文本及相关 ID 形成 SHA-256 指纹；任何成员关系、Workspace 归属、对象存在性、来源关系或指纹变化都使材料失效。失效时清除 continuation，并返回 `continuation_material_invalid`，要求重新核验。

### 5. 状态与工作台只表达真实可恢复能力

收尾失败原因沿用 `StopState`/`finalization`/`completion`：分别记录预算、`finalize_tool_attempted`、输出校验、超时、Provider/系统故障和 `continuation_material_invalid`。若当前材料包含 Evidence，确定性文案明确“来源已取得，可信度分析尚未完成”；只有 completion 中确实带 `finalize_answer` continuation 时才提示“说继续仅重试最终回答”。前端增加对应原因标签和续执行文案，不创建新的视觉结构或通用任务界面。

### 6. 回答依据贯穿 finalizer 与 answer-only continuation

`LoopState` 在每轮开始时确定回答依据：默认允许使用经授权的 Grove 材料；用户以高置信表达明确要求“抛开/不使用知识库”时切换为 `model_only`。该值不是新的意图分类，而是已有确定性资料工具禁用边界的结构化表示，并传入独立 finalizer、输出校验与 continuation。它只关闭 Grove 资料路径，不放宽外部核验、写入、Workspace 或对象权限。

`model_only` finalizer 从结构化历史中只装配用户原话、必要顺序、普通回答的有界结论与后续建议；历史 ToolCall/ToolReturn、授权结果集合、Entry/Evidence 引用元数据及程序侧材料均不进入请求。finalizer 获得显式动态指令：可以基于通用知识给出带边界的分析，但不得声称查询、核验或引用 Grove，不得输出 Entry、Evidence、列表或统计块。输出校验再次执行相同约束，避免提示词成为唯一防线。

若 `model_only` finalizer 仍因输出校验、超时或系统故障失败，即使本轮没有 Grove 材料，也建立最小 answer-only continuation。它只保存原始问题、已解析对象的有界叙述上下文、`model_only` 策略、完成/待办步骤和 Workspace/用户作用域；公开快照不返回完整上下文。收到“继续”或“下一轮继续”时先恢复该策略并直接调用 finalizer，不调用数据库材料复验或任何资料工具；主题切换仍清理旧待办。数据库材料 continuation 继续沿用既有指纹复验，两种模式都只允许一次最终回答请求。

### 7. 组合式候选稿交付语义

候选稿识别继续采用确定性高置信规则，不增加意图模型，也不枚举完整句子或业务主题。程序分别识别“补充、完善、改写、整理、优化”等修改动作和“发给我、给我看看、给我一版”等文本交付或审核信号；两类信号同时出现时，允许中间插入条目指代、知识名称等对象描述，并按候选文本请求处理。在没有明确要求 Agent 写入的前提下，既有“供我审核”“我自己更新”等明确由用户接手的表达继续视为候选请求；“我自己更新”这类明确主语归属可消除句中“更新知识库”造成的歧义。

明确要求 Agent “直接更新知识库”、保存、覆盖或写入正式记录的表达仍优先进入不支持边界；普通的“发给我”本身不足以推断为候选修改。候选路径只允许输出带“尚未写入”、原记录要点、建议补充、候选版本和来源边界的文本，不新增写入工具或数据库事件。模型若在已确定的候选请求中误调用 `report_unsupported`，沿用现有至多一次的合法纠正，不放宽请求、工具或时间预算。

### 8. V4 非思考模式与收尾协议收敛

`deepseek-v4-flash` 的 Chat Completions 默认开启 high 思考，而旧 `deepseek-chat` 兼容名对应非思考模式。统一对话循环在普通 Agent 与独立 finalizer 的请求设置中显式传入 `extra_body.thinking.type=disabled`；只对 DeepSeek V4 模型名生效，其他模型和离线 FunctionModel 不附加 Provider 专用参数。现有 temperature、输出上限、9000/12000 输入边界和请求次数均不改变。

Finalizer 提示明确唯一合法顶层为 `DialogueAnswer.blocks`，禁止自创 `answer_summary`、`completion` 等结构。为兼容已观察到的无权限含义格式偏差，`text` 块允许最多 500 字的可选 `note`，但程序不渲染、不保存为引用且不赋予任何权限。

真实 V4 响应还会在内容和引用已经完整时使用旧式 `answer_summary + completion` 外壳，且该偏差同时出现在普通求解和 finalizer。适配放在两者共用的 `BudgetedModel` 响应边界、框架决定格式重试之前：保留 Provider 原始公开响应，只有单一文本响应、顶层恰好符合受支持旧结构时才转换为唯一输出工具调用。`answer_summary.narrative` 必须是非空有界文本，`references` 只能转换为既有输出块类型；模型提供的 `completion` 只验证形状后丢弃，公开完成状态仍由程序根据转换后的 `DialogueAnswer` 与当前执行状态计算。

转换只负责语法映射，不授予材料权限。Evidence 的模型声明元数据作为待校验声明随兼容事件保留，转换结果继续经过同一个 `output_errors`，由当前轮真实 Evidence 句柄解析权威 Entry/Source 关系；错误句柄、关系不一致、把 Entry 结果冒充 Evidence、历史、伪造、未授权或跨 Workspace 引用仍原样拒绝。每次模型请求前清理上次临时声明，避免跨请求污染。转换不触发第二次模型请求，也不成为资料工具响应或其他任意 JSON 的宽松解析器；旧的 finalizer 事后恢复逻辑收敛到这一处统一边界。

### 9. 续执行真值与精简候选稿

公开 `can_continue` 由 continuation 是否真实存在派生，不再表示“用户可以重新问一次”。上一轮明确失败、未执行或部分完成且没有活动 continuation 时，收到“继续”类精确表达后程序直接返回 `continuation_not_available`，模型调用和资料工具执行都为零，避免把空指令交给普通 Agent 后重新读取历史材料；正常完成轮次后的自然“继续”仍可作为普通多轮承接。已有合法 continuation 的复验、只重试回答和材料失效行为保持不变。

候选修改的交付信号增加与修改动作组合使用的“输出”；当用户明确说“只/就输出补充后的知识内容，其他不用”时，程序标记为精简候选稿：只允许一个 text 块，包含候选正文、尚未写入声明和简短来源边界，不输出 list、statistic 或 evidence 块，从而避免渲染器展开完整 Source 原文。普通候选稿仍保留原记录要点、建议补充和修改后候选版本的分区要求。

## Risks / Trade-offs

- [1200 字符摘要可能遗漏较早回答细节] → 首尾保留并把对象、状态、决定和后续建议独立结构化；完整材料仍在程序侧按需装配。
- [直接数据库复验与工具合同重复一部分校验] → 复验仅判断已保存材料能否复用，不生成新 Evidence、不消费资料工具预算，并覆盖相同 Workspace/对象/来源边界。
- [工作台服务重启会丢失可续材料] → 明确限定同进程刷新恢复；旧运行继续只读，避免宣称不可实现的持久化恢复。
- [模型可能输出未声明的工具名] → Instrumentation 在响应离开模型层前识别并终止，测试断言资料工具实际执行次数为零且请求数为一。
- [首次 9000–12000 请求会增加一次正常模型调用机会] → 仍受硬门禁及所有冻结预算约束，并在诊断中记录首次请求软阈值例外。
- [无资料 continuation 可能把过时讨论带入新问题] → 仅响应明确继续表达，保存有界叙述上下文；其他输入一律按主题切换清理，不自动恢复。

## Migration Plan

仅修改实验循环和工作台，不涉及数据库迁移。实施后先用 FunctionModel 和隔离数据库测试验证，再运行后端、前端与 OpenSpec 静态检查。若回滚，恢复本 change 的本地提交即可；工作台历史 JSON 继续兼容新增的可选诊断字段。

## Open Questions

无。跨服务重启的 continuation 恢复、分页与其他第四批效率事项留在本 change 之外。
