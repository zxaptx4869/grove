## ADDED Requirements

### Requirement: 历史必须从结构化状态确定性压缩
实验统一循环 MUST 从回答块、工具事件和程序侧对象状态重建历史，而不是把完整渲染回答直接写回模型上下文。历史 MUST 保留用户原话与对话顺序、有界回答结论和后续建议、用户决定、授权列表的 Entry ID/标题/顺序/范围、已读取或核验对象的 Entry/Source 关系与状态，以及未完成步骤和必要错误；已展开的 Entry 正文和 Evidence 原文 MUST 仅保存在程序侧，不得随历史逐轮重复。单轮回答摘要与整体历史 MUST 使用确定性大小边界，不得调用摘要模型；必要上下文经压缩仍超过硬上限时 MUST 不派发并准确说明限制。

#### Scenario: 上轮展开正文和来源后继续追问
- **WHEN** 上轮回答包含完整 Entry 正文、Evidence 原文、可信度结论和下一步查询建议
- **THEN** 下一轮历史保留结论、建议、Entry/Source 标识及状态，但不包含已经展开的完整正文或 Evidence 原文副本

#### Scenario: 保留列表顺序和后续承接
- **WHEN** 历史中已有按授权集合展示的等级列表，用户先按“第二个”追问再按“第一条”追问
- **THEN** 程序侧仍保留同一授权列表顺序，第一条解析为真实 ENF Entry，且结构化历史保留足够的讨论结论与承接信息

#### Scenario: 候选稿和用户决定经过压缩
- **WHEN** 用户讨论候选修改稿、明确尚未写入或确认后续动作
- **THEN** 压缩历史保留候选性质、用户决定与必要上下文，不把候选内容误记为已写入正式 Entry

#### Scenario: 最小必要历史仍超过硬上限
- **WHEN** 用户原话、必要对象映射和当前完整请求投影经确定性压缩后仍超过 12000
- **THEN** 系统不派发模型请求，保留程序侧状态并明确说明无法在硬上限内安全保留必要上下文

### Requirement: 软阈值只限制本轮后续正常请求
系统 MUST 保持 9000 输入软阈值与 12000 硬上限不变。本轮第一次正常模型请求在完整投影不超过 12000 且其他预算允许时 MUST 可以派发，不得仅因达到 9000 直接进入 finalize；本轮后续正常请求达到 9000 时 MUST 停止资料循环并进入收尾，不论此前工具成功、失败、空结果或参数纠正。完整投影 MUST 包含当前 instructions、用户消息、历史、可见工具 schema 和必要材料；超过 12000 的请求 MUST NOT 派发。

#### Scenario: 首次请求位于软硬阈值之间
- **WHEN** 本轮第一次正常请求的完整投影输入为 9000 至 12000 之间且其他预算允许
- **THEN** 系统派发该正常请求，并记录它使用首次请求软阈值例外而未提高任何预算数值

#### Scenario: 首次请求超过硬上限
- **WHEN** 本轮第一次正常请求的完整投影超过 12000
- **THEN** 系统不派发请求，并以输入硬上限原因结束或确定性兜底

#### Scenario: 后续请求达到软阈值且没有成功材料
- **WHEN** 本轮已派发过正常请求，工具失败、返回空结果或参数纠正后下一次正常请求达到 9000
- **THEN** 系统仍停止资料循环并进入唯一一次收尾，不以没有成功材料为由继续请求

### Requirement: Finalizer 必须在程序级隔离资料工具
收尾阶段 MUST 使用独立的无资料工具 Agent 或执行器，只允许 `DialogueAnswer` 结构化输出和既有确定性校验，不得注册或执行搜索、目录、Entry、Evidence 等资料工具。Finalizer MUST 复用既有模型配置、一次收尾请求预算、授权结果集合、来源边界与输出校验，不得新增模型或放松第三批限制。模型若输出资料工具调用，程序 MUST 不执行该工具、记录 `finalize_tool_attempted` 并立即确定性兜底，不得追加第二次模型请求。

#### Scenario: 收尾输出 read_evidence
- **WHEN** finalizer 的唯一模型响应请求 `read_evidence(entry_id=7, source_ids=[66,89])`
- **THEN** `read_evidence` 实际执行次数为零，收尾原因记录为 `finalize_tool_attempted`，不派发第二次模型请求

#### Scenario: 收尾输出合法最终回答
- **WHEN** finalizer 只引用本轮已确认且仍获授权的结果或 Evidence 句柄并输出合法 `DialogueAnswer`
- **THEN** 程序按既有渲染和引用校验生成回答，不把来源内容夸大为官方交叉验证

#### Scenario: 收尾输出非法或超时
- **WHEN** finalizer 输出非法句柄、结构不合法、请求超时或发生 Provider 故障
- **THEN** 程序不追加第二次模型请求，并确定性展示可展示的已确认材料及具体缺口

#### Scenario: 明确不使用知识库后转入收尾
- **WHEN** 用户明确要求抛开知识库，普通阶段输出校验失败并在后续请求达到软阈值后转入 finalizer
- **THEN** finalizer 继承 `model_only` 回答依据，只接收必要的有界叙述上下文，不接收历史 ToolCall、ToolReturn、授权列表或 Entry/Evidence 句柄，并可基于通用知识完成带边界的回答

#### Scenario: 无资料 finalizer 尝试引用历史记录
- **WHEN** `model_only` finalizer 输出 Entry、Evidence、正式记录列表或声称已查询 Grove
- **THEN** 程序拒绝该输出，不执行任何资料工具，不把历史材料引用渲染给用户，也不追加第二次模型请求

### Requirement: 已取得材料的最终回答必须可续执行
当搜索、Entry 或 Evidence 材料已经成功取得，但最终回答因非法工具尝试、输出校验失败、超时或系统故障未完成时，系统 MUST 保存 finalize-only continuation。该状态 MUST 包含原始待完成问题、已解析指代、授权集合与范围、已成功读取材料的可恢复副本、Entry/Source/Attachment 关系及材料指纹、已完成步骤和唯一待完成的最终回答步骤；公开快照 MUST 只暴露有界元数据，不重复泄露完整正文。用户明确说“继续”且没有切换主题时，系统 MUST 先复验 Workspace 成员关系、对象归属、授权集合、来源关系与材料指纹，再只重试最终回答，不得重新搜索或重复调用成功的 `read_entries`/`read_evidence`。

#### Scenario: Evidence 成功但最终回答失败后继续
- **WHEN** ENF 的两个 Evidence 已成功取得，而最终可信度分析未完成，用户下一轮明确说“继续”
- **THEN** 系统复用仍有效的程序侧材料，只派发一次 finalizer 请求，语义搜索与 `read_evidence` 的新增执行次数均为零

#### Scenario: continuation 在工作台刷新后继续
- **WHEN** 浏览器刷新但实验服务进程和该对话运行上下文仍然存在
- **THEN** 工作台从服务端恢复可继续提示，提交“继续”后使用内存中的可恢复材料；服务重启后的旧对话仍按既有规则只读且不宣称可恢复

#### Scenario: 用户切换主题
- **WHEN** 存在 finalize-only continuation 而用户提出不同主题或新的查询
- **THEN** 系统不强制恢复旧任务，按新请求执行，并清除不再适用的旧待办状态

#### Scenario: 材料或权限已经失效
- **WHEN** Workspace 成员权限撤销、对象删除或移出范围、句柄伪造、Entry/Source 关系变化、Attachment 或材料内容版本变化
- **THEN** 系统拒绝复用旧材料，说明具体失效原因并转为需要重新核验，不把失效 continuation 表达为已取得有效部分结果

#### Scenario: 续执行成功
- **WHEN** finalizer 使用有效 continuation 生成并通过校验的最终回答
- **THEN** 系统清理待办状态，后续“继续”不重复执行已经完成的旧任务

#### Scenario: 无资料最终回答失败后继续
- **WHEN** 用户明确要求不使用知识库，finalizer 因输出非法、超时或系统故障未完成，且本轮没有 Grove Entry 或 Evidence 材料
- **THEN** 系统保存只含原始问题、必要有界叙述上下文、作用域和 `model_only` 策略的 answer-only continuation，不把参数错误或未执行查询伪装为已取得资料

#### Scenario: 下一轮继续无资料回答
- **WHEN** 存在有效的 `model_only` answer-only continuation，用户输入“继续”或“下一轮继续”
- **THEN** 系统恢复不使用知识库的约束并只调用一次 finalizer，新增搜索、Entry 读取和 Evidence 读取次数均为零；成功后清理 continuation

### Requirement: 部分完成状态必须与真实可恢复能力一致
已取得来源但未完成分析时，轮次 MUST 表达“来源已取得，分析尚未完成”，并且只有实际保存可恢复 continuation 时才提示用户说“继续”。没有可展示材料、参数错误或资料工具未执行时 MUST NOT 伪装为有效部分完成。原因码 MUST 区分预算边界、`finalize_tool_attempted`、输出校验失败、超时、系统故障和材料失效，同时复用现有状态机制，不另建通用任务系统。

#### Scenario: 来源已取得但可信度分析未完成
- **WHEN** 当前轮成功读取来源而 finalizer 未生成合法可信度分析
- **THEN** 状态为部分完成，展示已确认来源及“可信度分析尚未完成”，并提供与真实 finalize-only continuation 一致的继续提示

#### Scenario: 没有可恢复材料
- **WHEN** 查询参数非法、搜索未执行或当前轮没有任何可展示的已确认材料
- **THEN** 状态不得声称来源已取得或可以仅续执行最终回答

### Requirement: 第三批授权集合与只读边界不得回退
本 change MUST 保持直接相关授权集合、间接和不相关内容默认不展示、位置指代、语义搜索去重、目录定位、统计口径、正文展示、Workspace 隔离和候选稿只读边界。AI 输出仍仅为候选，MUST NOT 自动修改正式 Entry；固定 FunctionModel 或离线测试通过 MUST NOT 被报告为真实模型自然语言理解或答案质量通过。

#### Scenario: 四轮现场离线回归
- **WHEN** 以“甲醛是什么 → 解释这些等级 → 第二个可信吗 → 第一条可信吗”构造固定离线回归
- **THEN** 授权列表顺序保持不变、第一条映射到 ENF、间接和不相关内容不展示，且测试结论仅覆盖合同和执行边界

#### Scenario: 候选修改稿与正式记录
- **WHEN** 用户要求生成候选修改稿或要求直接写入正式记录
- **THEN** 前者仍明确尚未写入，后者仍不受支持，Entry 与 Source 不发生自动修改

#### Scenario: 对象描述插入候选补充表达
- **WHEN** 用户说“按你的分析，帮我把第一条的知识补充一下，发给我”或使用等价的修改动作与文本交付、审核表达，且没有要求程序直接保存、覆盖或写入正式记录
- **THEN** 系统 MUST 将请求识别为候选稿生成，允许中间包含条目指代或知识名称，输出明确尚未写入的候选文本，不得调用写入能力或报告为正式 Entry 写入不支持

#### Scenario: 带交付要求的直接写入
- **WHEN** 用户明确要求直接更新、保存、覆盖或写入知识库，即使同时要求“发给我”
- **THEN** 系统 MUST 保持只读边界并报告写入不支持，不得因交付表达将其降格为候选稿请求

### Requirement: DeepSeek V4 对话模式必须明确且预算不变
统一对话循环使用 `deepseek-v4-flash` 时 MUST 在普通求解与独立 finalizer 请求中显式关闭思考模式，以保持旧 `deepseek-chat` 非思考行为；其他模型 MUST NOT 接收 DeepSeek 专用参数。模型名、9000/12000 输入边界、输出、请求、工具、Entry、Evidence、批次和时间预算 MUST 保持不变。

#### Scenario: V4 求解和收尾请求
- **WHEN** 普通 Agent 和 finalizer 使用模型名 `deepseek-v4-flash`
- **THEN** 两者的模型设置均包含 `thinking.type=disabled`，且冻结预算快照与本 change 修改前一致

#### Scenario: 非 DeepSeek V4 模型
- **WHEN** 离线 FunctionModel 或其他模型构造统一对话 Agent
- **THEN** 程序不附加 DeepSeek 专用 `thinking` 请求体

### Requirement: 续执行提示必须对应真实可恢复状态
系统 MUST 仅在实际保存合法 continuation 时公开 `can_continue=true`。上一轮明确失败、未执行或部分完成但没有活动 continuation 时，收到精确的“继续”类表达后系统 MUST 返回不可恢复状态，模型和资料工具执行次数均为零；不得把该表达交给普通 Agent、重新搜索或重复读取历史成功材料。上一轮正常完成时的自然“继续”仍可按普通多轮对话处理。

#### Scenario: 有效 continuation 继续
- **WHEN** 上一轮保存了仍有效的 finalize-only continuation，用户说“继续”
- **THEN** 系统仍只复验并重试最终回答，`can_continue` 与公开 continuation 一致，不重复搜索、Entry 或 Evidence 读取

#### Scenario: 没有 continuation 的继续
- **WHEN** 上一轮失败、未执行或部分完成且公开状态没有 continuation，用户单独说“继续”或“下一轮继续”
- **THEN** 系统返回 `continuation_not_available` 且 `can_continue=false`，文本模型、搜索、Entry 与 Evidence 工具新增执行次数均为零

### Requirement: 收尾格式兼容不得放宽引用边界
系统 MAY 确定性忽略 text 块最多 500 字的可选备注，也 MAY 在 finalizer 唯一响应的内容与引用完整时，将已知旧式 `answer_summary + completion` 外壳确定性转换为 `DialogueAnswer`。该转换 MUST 仅接受非空有界叙述与受支持引用类型，MUST 丢弃模型自报的完成状态，并 MUST 将转换结果交给既有当前轮句柄授权、类型、来源和 Workspace 校验。系统 MUST 继续拒绝其他错误顶层结构、错误句柄类型、历史结果、伪造引用及未授权或跨 Workspace 材料。Finalizer MUST 被明确要求只输出 `DialogueAnswer.blocks`，不得通过增加模型重试兼容非法输出。

#### Scenario: text 块包含无害备注
- **WHEN** finalizer 输出合法 text 内容并额外携带不参与展示的 `note`
- **THEN** 程序忽略该备注并继续按 text 内容校验和渲染，不新增引用、材料或权限

#### Scenario: 已知旧式收尾外壳包含完整回答
- **WHEN** finalizer 唯一响应以 `answer_summary.narrative` 提供非空回答，并在 `answer_summary.references` 中引用本轮已确认且获授权的 Evidence，同时额外提供模型自报的 `completion`
- **THEN** 程序在不追加模型请求的情况下将叙述和引用转换为标准回答块，忽略模型自报完成状态，经既有输出校验通过后由程序判定完成，并记录兼容事件

#### Scenario: 旧式收尾外壳包含非法引用
- **WHEN** 已知旧式外壳引用历史 Evidence、伪造句柄、错误类型或未授权、跨 Workspace 材料
- **THEN** 转换后的回答仍被既有输出校验拒绝，不猜测或替换句柄，不执行资料工具且不追加模型请求

#### Scenario: 未知错误顶层结构
- **WHEN** finalizer 输出既不是 `DialogueAnswer` 也不是受支持的旧式外壳
- **THEN** 程序保持现有非法输出与 continuation 机制，不将任意 JSON 宽松转换为回答

#### Scenario: 错误引用不能被兼容
- **WHEN** finalizer 把 Entry 结果句柄当作 Evidence、引用历史列表或输出其他错误句柄
- **THEN** 程序仍拒绝该输出并按现有部分完成或 continuation 机制处理，不自动猜测或转换句柄

### Requirement: 精简候选稿请求不得展开来源原文
用户在候选稿上下文中明确要求“只输出补充后的知识内容，其他都不用”时，系统 MUST 只展示一个有界 text 块，保留“尚未写入”和模型补充不属于 Source 原文的边界，不得输出或渲染 list、statistic、Entry 正文引用或 Evidence 块。普通候选稿分区和正式 Entry 只读边界保持不变。

#### Scenario: 只输出补充后的内容
- **WHEN** 用户说“就输出你补充后的知识内容就行，其他的都不用”
- **THEN** 系统识别为精简候选稿，只返回候选正文与必要边界，不展开已读取 Evidence，不修改正式 Entry
