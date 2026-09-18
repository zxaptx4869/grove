# knowledge-agent-dialogue-loop-production-adapter Specification

## Purpose
TBD - created by archiving change knowledge-agent-dialogue-loop-production-adapter. Update Purpose after archive.
## Requirements
### Requirement: Web Agent SHALL use the unified dialogue loop as its only orchestration core

正式 Web Agent SHALL 使用统一对话循环完成模型请求、只读工具调用、结果选择和收尾；同一轮 SHALL NOT 先后执行旧多级规划链与统一循环。

#### Scenario: Simple answer bypasses legacy planning graph

- **WHEN** 用户提交不需要知识库资料的身份或普通问题
- **THEN** Web Agent 通过统一循环完成回答，且运行记录不包含旧多级规划阶段的调用

#### Scenario: Knowledge query uses one unified tool loop

- **WHEN** 用户提交项目、统计、Entry、Evidence 或候选稿相关问题
- **THEN** Web Agent 由统一循环按需调用工具并执行程序级收尾，返回可辨识的轮次状态

### Requirement: Production adapter SHALL preserve formal identity and isolation

适配器 SHALL 从正式 Conversation、用户、Workspace 和授权范围构造循环状态，并在每次工具和恢复操作前复验身份、Workspace、项目、目录、Entry 和 Source 归属。

#### Scenario: Authorized conversation is restored

- **WHEN** 已认证用户向属于其 Workspace 的 Conversation 提交新轮次
- **THEN** 循环获得相同用户和 Workspace 范围，历史只来自该 Conversation

#### Scenario: Cross-workspace reference is rejected

- **WHEN** 请求或 continuation 指向不属于当前 Workspace 或用户的对象
- **THEN** 适配器拒绝执行并返回明确失败或拒绝状态，不调用模型生成伪造结果

### Requirement: Production adapter SHALL persist recoverable turn state

适配器 SHALL 保存用户消息、回答块、工具和模型可观测记录、终态、未完成步骤及最小 continuation；恢复 SHALL 只重试未完成步骤。

#### Scenario: Finalization fails after successful read

- **WHEN** Entry 已成功读取但最终回答生成失败
- **THEN** 轮次为 `partial_completed`，保留已确认材料并保存只需重试最终回答的 continuation

#### Scenario: Continue retries only the pending step

- **WHEN** 用户在可恢复轮次中请求继续且身份、Workspace 和对象校验通过
- **THEN** 系统不重复成功搜索或读取，只执行 continuation 标记的未完成步骤

#### Scenario: Service restart cannot restore unsafe in-memory state

- **WHEN** 服务在轮次中重启且没有可安全恢复的持久化状态
- **THEN** 系统返回明确的不可恢复状态，不把中断轮次伪装成已完成

### Requirement: Answer blocks and terminal states SHALL remain type-safe

正式 API SHALL 保留统一循环的真实结果类型和终态，客户端不需要从自然语言或句柄猜测展示含义。

#### Scenario: Structured result is returned

- **WHEN** 工具返回项目列表、统计、Entry、Evidence 或候选稿
- **THEN** API 使用对应结构化块和真实结果元数据返回，不把一种结果类型包装成另一种

#### Scenario: Empty exact result completes normally

- **WHEN** 精确查询已成功执行且结果为空
- **THEN** 轮次为 `completed` 并明确返回零条或无记录，不因其他未执行候选工具把整轮错误标成部分完成

#### Scenario: Invalid tool parameters are distinguishable

- **WHEN** 某工具参数非法且没有可确认的成功结果
- **THEN** 轮次明确为参数错误对应的失败或部分完成状态，并列出具体缺口

### Requirement: Agent output SHALL remain candidate-only

统一循环接入正式 API 后，模型生成的补充、整理和修改 SHALL 仍只能作为候选，不得自动覆盖正式 Entry。

#### Scenario: Candidate draft is delivered

- **WHEN** 用户要求围绕当前 Entry 生成候选补充或修改稿
- **THEN** API 返回候选块并保留当前 Entry 与来源边界，不执行正式 Entry 写入

### Requirement: Production adapter SHALL expose auditable execution metadata

适配器 SHALL 记录 provider、model、fallback 状态、工具顺序、终态和 continuation 原因；成功响应 SHALL NOT 静默掩盖模型调用失败或确定性降级。

#### Scenario: Model fallback is visible

- **WHEN** 统一循环无法完成模型调用并使用确定性兜底
- **THEN** 运行记录标记 fallback 及原因，API 状态或可审计记录可识别该降级

### Requirement: Grove Web SHALL be a thin client of the formal Agent API

Grove Web SHALL use the formal Conversation, Message, Run, cancel and observability APIs; it SHALL NOT call the experiment workbench service, persist experiment JSON, or implement a second orchestration path.

#### Scenario: Agent entry opens a formal conversation

- **WHEN** authenticated user opens the Knowledge Agent entry in the Grove sidebar
- **THEN** the page lists or creates a formal Workspace conversation and restores its messages through the formal API

#### Scenario: Active Run is polled without duplicate messages

- **WHEN** a submitted Run is waiting or processing
- **THEN** the client refreshes the formal message page until a terminal state and renders each user/assistant message once by server IDs

### Requirement: Web SHALL render result blocks and terminal states by contract

The Web client SHALL render `text`, `list`, `statistic`, Entry, Evidence, candidate and insufficient blocks from API type fields, and SHALL expose completed, partial, not-executed, unsupported, failed and continuation states without inferring from titles, natural language or handles.

#### Scenario: Structured results keep their types

- **WHEN** a Run returns a project list, statistic, Entry, Evidence or candidate block
- **THEN** the corresponding result view is rendered and project lists, statistics, Entries and candidates remain visibly distinct

#### Scenario: Continuation is explicit

- **WHEN** a terminal Run returns `can_continue=true`
- **THEN** the assistant message exposes a Continue action that submits a formal next message; it does not copy or mutate continuation state in the browser

### Requirement: Web SHALL remove the diagnostic side rail

The formal Grove Agent page SHALL omit the experiment workbench right-side runtime status panel while retaining backend observability and showing only compact per-message execution details where useful.

#### Scenario: No right runtime panel is rendered

- **WHEN** the Agent page is rendered
- **THEN** only the Grove app shell, conversation list and chat area are shown; provider, budget, snapshot and runtime diagnostics are not rendered as a side panel

### Requirement: Unified production orchestration SHALL be independent from legacy executors

正式 Worker、`production_adapter`、Candidate、Entry Revision 与只读搜索 SHALL NOT import or invoke the retired Knowledge Agent runner or its planning graph. Shared cancellation control SHALL remain available from a module without answer-orchestration responsibilities.

#### Scenario: Formal answer Run executes after retirement

- **WHEN** Worker claims an ordinary answer Run
- **THEN** it invokes `production_adapter` and the unified dialogue loop without importing the retired runner
- **AND** cancellation at an existing safe boundary still produces the same cancelled terminal state

#### Scenario: Operation Run keeps cancellation behavior

- **WHEN** a Candidate or Entry Revision Run observes a committed cancellation request
- **THEN** the operation raises the shared cancellation signal and Worker finalizes it as cancelled
- **AND** no legacy answer executor is loaded

### Requirement: Legacy execution snapshots SHALL NOT enter the unified loop

The Worker MUST distinguish current unified-loop recovery state from retired execution checkpoints. A stale answer Run with a legacy or unknown execution step SHALL fail with an explicit recovery reason and MUST NOT be requeued into `production_adapter`; historical data SHALL remain readable.

#### Scenario: Legacy processing snapshot expires

- **WHEN** an answer Run exceeds its lease with a legacy planner, investigation, composite, coverage, or shared-graph step
- **THEN** Worker marks the Run failed and releases its active slot
- **AND** it does not invoke the unified loop or mutate historical execution records

#### Scenario: Current operation Run expires

- **WHEN** a Candidate or Entry Revision Run exceeds its lease within the existing retry limit
- **THEN** Worker retains the existing idempotent operation recovery behavior

### Requirement: 软阈值停止不得丢失可安全交付内容

统一 dialogue-loop 在输入投影达到 9000 软阈值但未达到 12000 硬上限时 MUST 停止新增搜索、读取和其他资料动作，并 MUST 允许既有无工具 finalizer 根据已确认对话、已授权材料及同轮已经通过对应内容边界检查的文本完成收尾。未筛选语义候选 MUST 保持不可展示、不可引用且不得被解释为空结果；完成状态 MUST 依据实际交付和剩余步骤决定，不得统一改为 `completed`。

#### Scenario: Run 13 整理请求在软阈值处安全收尾

- **WHEN** 首次请求投影 8295 并成功完成项目上下文和返回 5 条未筛选候选的搜索，下一求解请求投影 9290
- **THEN** 系统不再派发资料动作，而由无工具 finalizer 使用已确认对话解释不能直接保存正式 Entry 并可提供候选稿
- **AND** 回答不包含 5 条候选、列表块或“0 条结果”，终态按实际回答和未完成筛选判断

#### Scenario: 依赖候选的任务仍然部分完成

- **WHEN** 用户问题必须依赖 5 条语义候选才能回答，而软阈值在相关性选择前触发
- **THEN** 系统不把候选作为直接相关结果，不声称查无结果，并准确返回相关性筛选未完成及可恢复状态

#### Scenario: 硬上限和真实模型失败保持原保护

- **WHEN** 必要输入仍超过 12000 硬上限，或真实模型请求已经派发后由 Provider 失败
- **THEN** 系统分别按输入硬边界或真实模型失败停止，不以无工具收尾伪装成功，也不提高任何冻结预算

### Requirement: 未筛选候选续执行只恢复未完成步骤

任务依赖未筛选候选时，系统 MUST 保存最小 `relevance_selection` continuation，包括原问题、候选句柄及内容指纹、成功查询摘要、Workspace/用户/项目范围和对象校验引用。用户明确继续时 MUST 重新校验 Workspace、权限、项目范围、候选 Entry 和句柄内容，仅恢复相关性选择及其后的最终回答；成功搜索 MUST NOT 重复派发。校验失败 MUST 准确终止恢复且不得授权旧候选。

#### Scenario: 继续完成筛选而不重复搜索

- **WHEN** 有效的 `relevance_selection` continuation 保存了成功搜索和 5 条未筛选候选，用户说“继续”
- **THEN** 系统复用原候选完成逐项 direct/indirect/unrelated 选择，再按授权结果收尾
- **AND** 新增搜索次数为零，间接与不相关候选不进入答案

#### Scenario: 权限或范围变化使恢复失效

- **WHEN** continuation 保存后用户失去 Workspace/Entry 权限、项目范围变化或候选对象版本改变
- **THEN** 系统返回 `continuation_material_invalid`，不重新搜索、不展示候选且不把 Run 标记为完成

#### Scenario: 候选句柄失效

- **WHEN** continuation 的候选句柄缺失、指纹不一致或不再属于原成功查询
- **THEN** 系统拒绝恢复，不猜测替代句柄也不重新执行成功查询

### Requirement: 跨轮已授权 Entry 读取必须恢复发现门禁

生产适配器在恢复上一轮状态时 MUST 将已授权、已发现且保存了 Entry 内容指纹的对象同步恢复到现有 `RunToolContext.discovered_entry_ids`；未筛选候选 MUST NOT 因此获得读取授权。每次读取仍 MUST 复验 Workspace 成员权限、项目范围、Entry 存在性和当前指纹；任一不一致 MUST 拒绝读取。同一组 Entry 的后续成功读取 MUST 消解同轮早先已被成功读取证伪的临时拒绝终态，真实权限失败仍 MUST 保持 `denied`。

#### Scenario: Run 786 授权集在 Run 787 首次直接读取

- **WHEN** Run 786 搜索、筛选并成功读取 Entry 35、18、84，Run 787 请求输出同三条内容
- **THEN** Run 787 首次 `read_entries([35,18,84])` 直接成功，本轮只读取一次且不派发 `search_knowledge`、`query_entries` 或 `select_relevant_entries`
- **AND** 最终状态为 `completed`，不保留已被后续成功读取消解的临时 `denied`

#### Scenario: 权限、范围或对象变化继续拒绝

- **WHEN** 恢复后的用户权限已撤回、Workspace 或项目范围不一致、Entry 已删除或当前指纹不同
- **THEN** 读取在返回正文前被拒绝或标记为不可用，不自动重搜也不放宽候选/直接相关授权边界

### Requirement: 结构化输出兼容必须严格且可恢复

统一模型包装层 MAY 对唯一输出工具参数形如 `{"INVALID_JSON": "..."}` 的已知 Provider 包装执行一次确定性解包，但仅在内层字符串可由标准 JSON 解析器严格解析、顶层恰为受支持的 `DialogueAnswer`、完整合同校验通过时才可转换。系统 MUST NOT 使用宽松 JSON 修复、正则提取、补括号或放宽 schema；解析或授权校验失败时 MUST 保留已确认材料及 finalize-only continuation，并且继续只重试最终回答而不重复成功资料动作。现有模型请求和重试预算 MUST 保持不变。

#### Scenario: 外层包装但内层合法

- **WHEN** Provider 将完整合法的 `DialogueAnswer` 放进唯一 `INVALID_JSON` 字符串字段
- **THEN** 系统严格解析并按原合同验证，在不增加模型请求的情况下接受结果并记录兼容事件

#### Scenario: 真实 INVALID_JSON 内层损坏

- **WHEN** 2026-09-16 实验台真实响应的外层包含 `INVALID_JSON`，而内层六点补充文本在 JSON 第 1120 列附近因未转义引号而无法严格解析
- **THEN** 系统拒绝该输出，不修复或提取正文，保留已确认材料并公开合法的 finalize-only continuation

#### Scenario: 解包结果引用未授权材料

- **WHEN** 内层 JSON 可解析但包含未筛选候选、历史句柄、跨 Workspace 对象或错误 Entry/Source 关系
- **THEN** 既有输出、权限与来源校验拒绝结果，兼容层不替换或授权引用

### Requirement: 格式重试和收尾必须保留已通过检查的内容

普通求解输出在格式或引用校验重试前，系统 MUST 保存其中已通过自身内容边界的文本块及其模型通用知识标注，并 MUST 将未通过的结构化块、未筛选候选和未经授权引用隔离。后续软阈值或 finalizer 失败时，系统 MUST 使用或保留该受限文本，不得由更弱的失败说明覆盖；未经完整校验的原始输出仍不得整体接受。

#### Scenario: 通用解释因待筛选候选触发重试

- **WHEN** 普通求解已生成带通用知识标注的完整概念解释，但同轮未筛选候选导致输出校验要求重试且下一请求触发软阈值
- **THEN** 无工具 finalizer 收到该已检查文本并保持通用知识边界，最终用户不只看到“知识库无法回答”

#### Scenario: 原输出混有未授权资料块

- **WHEN** 同一输出包含可保留通用文本以及引用未筛选候选的列表、Entry 或 Evidence 块
- **THEN** 系统只保存文本候选，丢弃未授权资料块并继续执行完整最终输出校验

### Requirement: 收尾转换和模型失败审计必须准确

`finalize_transition` 表示求解请求因程序停止点未派发，生产适配器 MUST 将其记录为 `not_dispatched`，保留 `input_soft_limit` 等停止原因、输入投影和零耗时，并 MUST NOT 标记为 fallback 或 `model_call_failed`。已派发后发生的 Provider、超时或协议失败 MUST 继续记录真实失败。

#### Scenario: 软阈值转换未派发

- **WHEN** 9290 输入投影触发 `finalize_transition` 且该求解请求没有发送给 Provider
- **THEN** 审计 outcome 为 `not_dispatched`、`is_fallback=false`，并保留 `finalize_reason=input_soft_limit`

#### Scenario: Provider 调用真实失败

- **WHEN** 文本请求已经派发且 Provider 返回错误或超时
- **THEN** 审计 outcome 仍为 `model_call_failed` 并保留原错误，不被归类成未派发

### Requirement: 校验异常不得摧毁失败恢复依据

确定性失败兜底 MUST 始终生成符合完整 `DialogueAnswer` 合同的输出，包括最多 12 个块的限制；当已确认材料超过展示容量时，系统 MUST 优先保留状态、已通过边界检查的文本和最终缺口说明，其余材料继续留在有界恢复快照而不得导致兜底再次抛异常。正式适配器捕获未处理异常时 MUST 保存脱敏诊断、已产生的模型与工具审计、已有授权材料及合法 continuation，不得用空失败快照覆盖恢复依据。

#### Scenario: Run 794 的失败兜底超过块上限

- **WHEN** “好的，你整理一下”的输出校验失败，兜底可展示材料原本会组成 13 个块
- **THEN** 系统确定性裁剪为不超过 12 个合法块，保留状态与缺口说明，并按实际失败或部分完成状态持久化
- **AND** 兜底自身不再抛 `DialogueAnswer.blocks too_long` ValidationError

#### Scenario: 未捕获异常保留脱敏现场

- **WHEN** 统一循环仍有未捕获异常越过共享兜底
- **THEN** 正式 Run 保存异常类型与结构化校验位置/类型、当轮已有模型和工具审计及可安全恢复状态
- **AND** 快照不保存 traceback、原始 prompt 或未经既有裁剪的模型响应

### Requirement: 失败后的新问题不得自动续做旧任务

上一轮失败后，系统 MUST 仅在用户明确请求 continuation 时激活安全恢复材料；用户提出新的独立问题时 MUST 清除旧失败任务的当前句柄和模型消息历史，只执行当前问题。该隔离 MUST NOT 放宽 Workspace、权限、项目范围、Entry 存在性、指纹或候选授权规则。

#### Scenario: Run 795 新问项目数量

- **WHEN** 上一轮候选整理失败后，用户另问“我有几个项目”而不是发出“继续”指令
- **THEN** 系统不续做候选整理，调用一次 `list_projects` 并根据返回结果正常回答
- **AND** 不因旧失败任务材料触发无查询的“缺少材料”收尾

#### Scenario: 明确继续恢复失败任务

- **WHEN** 上一轮保存了合法 continuation 且用户明确说“继续”
- **THEN** 系统按既有复验合同恢复该任务，不把 continuation 当作新的独立问题

### Requirement: 已有 Entry 候选失败后必须可安全续接

已有正式 Entry 的候选改写在最终校验失败时，系统 MUST 保存恢复当前任务所需的最小编辑对象定位信息、候选文本及校验缺口。用户明确续接时，系统 MUST 在重建编辑上下文前复验 Workspace、用户身份、项目范围、当前权限、对象存在性和 Entry/Source/来源关系指纹；复验通过后 MUST 只重试最终候选交付，MUST NOT 重复成功的搜索、Entry 读取、Source 读取或新增 Evidence。

#### Scenario: Run 801 的候选在 Run 802 继续完成

- **WHEN** Run 801 已经对单条授权 Entry 生成候选草稿，但最终边界校验未通过并保存 `candidate_draft` continuation，Run 802 明确说“继续”
- **THEN** 新 Run 完成数据库复验后从已验证的单条 Entry 恢复编辑上下文，只调用无工具 finalizer 并交付候选文本
- **AND** 不重复搜索、筛选、Entry/Source 读取或 Evidence 生成

#### Scenario: 续接前权限、范围或材料变化

- **WHEN** 恢复前 Workspace 成员权限被撤回、项目范围改变、Entry 被删除，或 Entry/Source/来源关系指纹不同
- **THEN** 系统返回 `continuation_material_invalid`，不调用模型、不重新搜索且不展示旧候选内容

#### Scenario: 失败后改问独立问题

- **WHEN** 上一轮保存了候选 continuation，用户下一轮提出新的独立问题而非明确续接
- **THEN** 系统不恢复旧编辑任务，只处理当前问题

### Requirement: 候选改写必须同时通过语义与边界校验

候选 finalizer MUST 获得当前 Entry、用户的改写限制和已保存候选。它 MUST 用自然、简短的表达区分现有记录、模型增补及未写入状态，但 MUST NOT 依赖固定章节或单纯关键词匹配。当用户只要求改语气、措辞或润色时，候选 MUST 保持原记录的事实关系、数量所属维度及程度/不确定性；不一致时 MUST 继续作为未通过候选，不得以结构合法代替语义验证。

#### Scenario: 口语化不得改变数量的尺寸含义

- **WHEN** 原记录包含“预留 20cm 防倒灌空间”，用户只要求口语化，而候选改为“留 20 公分高度”
- **THEN** 该候选因把“空间”收窄为“高度”而不能完成交付，系统保留草稿并说明语义缺口

#### Scenario: 口语化保留不确定性

- **WHEN** 原记录使用“建议”、“约”、“可能”等限定，候选在只改语气时将其改成无条件的确定结论
- **THEN** 语义校验拒绝该候选，且不通过补固定标题或边界关键词改变结果

### Requirement: 候选失败摘要必须聚焦当前任务

候选改写未通过时，用户可见失败输出 MUST 最多展示一次经安全复验的当前候选，并附上当前准确缺口和有效恢复方式。历史列表、无关记录、重复正文和内部恢复材料 MUST NOT 重放；现有 12 块上限和最终缺口说明 MUST 保留。

#### Scenario: 候选校验失败时不重放旧列表

- **WHEN** 当前候选因来源边界或语义保持未通过，而快照内仍有旧项目列表、多条 Entry 及同一 Entry 的重复句柄
- **THEN** 回答只展示当前候选一次、本轮校验缺口和“继续”恢复说明，不展示旧列表或重复正文

### Requirement: 已有 Entry 协作上下文必须跨成功 Run 安全衔接

生产适配器 MUST 仅对已授权且已读取的单个正式 Entry 保存有界协作上下文，包括对象定位、必要指纹、针对该对象的最近模型分析、最新安全候选和用户决定。下一 Run 只有在正常追问明确继续该对象时才可激活这些材料，且在进入模型输入前 MUST 复验 Workspace、用户、项目范围、当前权限、Entry 存在性及 Entry/Source/来源关系指纹。明确独立新任务 MUST NOT 自动绑定旧对象。该机制 MUST NOT 扩展为新建草稿或通用草稿记忆。

#### Scenario: 简短的通用知识追问承接已展示正文

- **WHEN** 上一轮已展示授权 Entry 正文，用户说“抛开知识库，第一条说得对吗”
- **THEN** 系统以刚展示的第一个对象为讨论对象，使用通用知识分析其实际正文，不要求用户重贴
- **AND** 不新增搜索、Entry/Source 读取或 Evidence，不把通用分析声称为来源核验

#### Scenario: 前轮分析进入同一 Entry 的候选生成

- **WHEN** 用户对已展示 Entry 完成通用知识分析后说“按刚才分析改”或等价追问
- **THEN** 候选 finalizer 的实际模型输入同时包含已复验的当前 Entry、前轮分析、用户决定和当前交付边界
- **AND** 候选落实用户采纳的分析，区分原记录、模型新增判断和未写入状态

#### Scenario: 独立新任务不误用协作上下文

- **WHEN** 上一轮存在已验证的 Entry 协作上下文，但用户明确提出与该对象无关的新任务
- **THEN** 系统只处理当前任务，不把旧分析、候选或用户决定注入本轮交付

### Requirement: 已读取 Entry 的材料合同必须跨工具一致

`read_entries` 与 `open_list_item` 产生的正文结果 MUST 使用一致的 Entry 身份、内容指纹、数据库校验引用及父展示集合/位置关系。列表发现 MUST 继续与正文读取区分，未读取列表项 MUST NOT 因存在于展示集合而获得正文材料身份。用户按位置追问时，系统 MUST 根据实际展示给用户的有界集合和稳定父子引用解析，不得仅截取最后若干内部工具结果。

#### Scenario: 批量读取后的第一条保持稳定

- **WHEN** 一个有序展示集合的多条 Entry 正文由 `read_entries` 返回，用户下一轮询问“第一条”
- **THEN** 系统把第一条解析为该展示集合中实际呈现的第一个 Entry，并携带其当前校验引用进入后续讨论

#### Scenario: 逐条打开不覆盖原展示顺序

- **WHEN** 系统依次用 `open_list_item` 打开展示集合中的三条正文，用户随后询问“第一条”
- **THEN** 三条正文结果均保留父集合与原位置，最后一次内部打开不得把“第一条”改指为第三条或使第一条从可解析窗口消失

### Requirement: 已授权展示集合必须允许合法保序子集读取

系统 MUST 允许 `read_entries` 读取同一已授权展示集合中的合法保序子集，并 MUST 使结果顺序与请求及父集合相对顺序一致。每个对象仍 MUST 逐项复验 Workspace、用户权限、项目范围、对象存在性及当前指纹；任意 ID 不属于该父集合、顺序不合法、属于未筛选候选或复验失败时 MUST 拒绝整个读取，不得扩大为任意发现对象读取。

#### Scenario: 从四条授权集合读取第一条

- **WHEN** 已授权展示集合为 `[7, 10, 9, 8]`，用户要求读取第一条且模型调用 `read_entries([7])`
- **THEN** 系统复验 Entry 7 后返回其正文，不要求同时读取其余三条，也不重新搜索或筛选

#### Scenario: 子集不能越过授权和顺序边界

- **WHEN** 读取请求包含父集合外对象、未筛选候选，或以不符合父集合相对顺序的方式组合多个 ID
- **THEN** 系统拒绝读取，且不因对象曾被其他历史结果发现而放宽范围

### Requirement: 成功的 Entry 分析必须由明确对象关联并跨 Run 传递

当 Agent 的成功回答明确关联到一个已展示且已复验的 Entry 时，普通直接回答与无工具 finalizer 回答 MUST 都能将该分析保存为该 Entry 的有界 discussion，并在后续候选模型输入中提供。程序 MUST 验证对象身份、展示关系、Workspace、权限、范围和材料指纹，但 MUST NOT 通过关键词路由猜测话题，也 MUST NOT 把任意上一轮回答自动挂接到旧焦点；无法唯一关联时 MUST 澄清或不保存关联。

#### Scenario: 普通直接分析进入后续候选

- **WHEN** 用户对已展示的明确 Entry 提出通用知识判断，Agent 直接成功回答，下一轮要求“按刚才分析改”
- **THEN** 后续候选输入包含同一 Entry、刚才成功分析、当前用户要求和未写入边界，不要求额外模型阶段或重复资料读取

#### Scenario: 自动模式切换对象或独立问题

- **WHEN** 用户在 `auto` 模式明确切换到另一已展示 Entry，或提出与原 Entry 无关的独立问题
- **THEN** 系统只在新对象可唯一复验时更新关联，独立问题不保存为旧 Entry 的 discussion，也不注入旧候选材料

### Requirement: 历史材料与本轮活动材料必须有界分离

生产适配器 MUST 区分跨 Run 可引用的历史 `result_sets` 与实际参与本轮校验、finalizer 和失败输出的活动材料。恢复状态时 MUST NOT 把全部历史结果无条件提升为 `current_handles`；系统 MUST 有界保留最近用户可见展示集合、其必要已打开子项和当前协作对象，以支持“第一条”“刚才那组”等引用。失败摘要 MUST 只展示当前任务的已确认材料，不得倾倒历史列表或正文。

#### Scenario: 新任务失败不重放历史材料

- **WHEN** 快照包含多个历史列表和正文，而当前任务在对象绑定或候选校验处失败
- **THEN** 失败输出只使用当前活动集合、明确绑定对象和本轮安全草稿，不展示与当前任务无关的旧列表或正文

#### Scenario: 有界恢复仍支持刚才那组

- **WHEN** 用户在下一 Run 引用最近实际展示的一组 Entry
- **THEN** 系统可从有界展示窗口解析该组及其顺序，但更早且与当前任务无关的结果不会自动进入活动句柄

### Requirement: 位置指代必须依据实际交付序列

系统 MUST 区分允许展示的工具结果与最终回答实际交付的结果。跨 Run 的位置指代和最近展示顺序 MUST 只由最终 `blocks` 引用的列表确认，并按历史中实际交付的先后排序，不得依赖每个新 Run 重置的 `turn_index` 或句柄字符串。已有快照即使历史 `turn` 全相同也 MUST 按历史数组顺序恢复；内部搜索、筛选或读取产生但未交付的列表 MUST NOT 静默替换用户的位置参照。新列表实际交付后 MUST 成为新的可引用顺序。存在多个已交付集合且无法唯一判断时 MUST 澄清，并继续执行 Workspace、权限、范围、对象存在性和指纹复验。

#### Scenario: 内部新列表不覆盖用户看到的顺序

- **WHEN** 用户看到列表 A，下一 Run 的内部筛选产生顺序不同的列表 B 但最终回答未引用 B，随后用户问“第二条”
- **THEN** 系统仍按 A 的第二条解析，不依据 B 或最后产生的内部句柄改写位置参照

#### Scenario: 交付新列表后更新顺序

- **WHEN** 顺序不同的列表 B 已经进入最终回答并展示给用户，随后用户问“第二条”
- **THEN** 系统按 B 的第二条解析；若 A 与 B 同时可能被指代且上下文不足，则请求澄清

### Requirement: 有用的 direct 与 indirect 相关记录必须统一展示

相关性筛选 MUST 保持 `direct` 与 `indirect` 的真实分类，在同一结果列表中优先排列 direct，再排列有实际帮助的 indirect，并排除 unrelated。indirect 项 MUST 附带简短性质或关联说明，不能被描述为直接回答；列表 MUST 只交付标题和必要说明，用户明确要求正文后才读取。相关性不得成为访问身份，Workspace、权限、项目范围、对象存在性和材料指纹 MUST 继续由现有访问边界复验。系统 MUST NOT 通过私有间接集合、专用激活参数或重新搜索同一问题建立第二套常规展示流程。

#### Scenario: 一次筛选统一展示有用相关标题

- **WHEN** 一次筛选得到 2 条 direct、2 条有帮助的 indirect 和 1 条 unrelated
- **THEN** 最终回答交付一个连续编号列表，2 条 direct 在前、2 条 indirect 在后，每条 indirect 标明其关联性质，unrelated 不出现
- **AND** 列表不包含正文内容，用户明确要求后才按同一列表位置读取

#### Scenario: 统一列表位置读取 direct 或 indirect

- **WHEN** 用户指定统一列表中的第 3 条或第 4 条
- **THEN** Agent 通过同一 `open_list_item` 合同按实际展示位置读取对应 Entry，并继续复验 Workspace、权限、范围、对象存在性和指纹
- **AND** 不重新搜索，不要求二次激活，不把 indirect 改报为 direct

#### Scenario: 统一相关结果安全条件失效

- **WHEN** 读取前权限被撤回、项目范围变化、对象删除或材料指纹变化
- **THEN** 系统拒绝返回正文，不用旧分类结果绕过安全检查

### Requirement: finalizer 必须保存明确关联的 Entry 分析

普通回答与无工具 finalizer 的成功输出 MUST 通过同一入口处理明确关联的 Entry discussion。输出包含可验证且确实已读取的 `discussion_entry_id` 时，系统 MUST 复验已展示/已读取身份、Workspace、权限、范围和材料指纹后保存分析；若 ID 只存在于标题列表而没有已读取正文，系统 MUST 记录简明跳过诊断并交付已通过正文/引用校验的回答；若已读取对象的安全复验失败，MUST 拒绝关联并保留安全错误。没有关联 ID 且没有活动对象时 MUST NOT 自动绑定旧焦点。finalizer 提示与输出 schema MUST 一致允许该可选关联字段，且不得为保存分析新增模型阶段或第二套讨论状态。

#### Scenario: 标题回答误填未读对象关联

- **WHEN** 标题列表回答的正文与引用校验通过，但模型额外填写了仅在标题列表中出现、尚未读取正文的 `discussion_entry_id`
- **THEN** 系统交付该回答、记录关联未保存的诊断，不创建 discussion，也不要求 continuation

#### Scenario: 已读对象安全复验失败仍拒绝关联

- **WHEN** `discussion_entry_id` 对应已读对象，但权限、范围、对象或材料指纹已失效
- **THEN** 系统拒绝保存关联并保留安全失败，不把真实安全问题降级为普通辅助字段错误

#### Scenario: 未预绑定对象的 finalizer 保存分析

- **WHEN** 当前没有预先激活的 `editing_context`，无工具 finalizer 对已展示且已读取的 Entry 返回成功分析及明确 `discussion_entry_id`
- **THEN** 系统经统一入口保存该 Entry 的 discussion，下一 Run 生成候选时实际模型输入包含这段分析

#### Scenario: 无关联 ID 不回绑旧焦点

- **WHEN** finalizer 回答新的独立问题且没有 `discussion_entry_id` 或活动对象
- **THEN** 系统不把回答保存到历史旧焦点，也不在后续候选中注入该回答

### Requirement: 否定的未写入说明不得被识别为正面写入声称

候选安全校验 MUST 拒绝真实的正式写入、确认或生效声称，但 MUST NOT 因局部否定明确覆盖这些状态而拒绝合理的“候选尚未写入”说明。检测 MUST 分别检查转折、新主语、独立句和引述中的正面声称；正文某处存在否定表达 MUST NOT 成为其他正面声称的全局豁免。该确定性规则 MAY 保持有限，MUST NOT 声称覆盖全部中文语义。

#### Scenario: 否定跨短主语覆盖并列状态

- **WHEN** 候选说明“不代表它已经过官方确认或已写入正式记录”且正文没有其他正面写入声称
- **THEN** 写入声明校验通过，不因此丢弃安全候选或额外要求 continuation

#### Scenario: 转折后的正面写入仍拒绝

- **WHEN** 输出先说“尚未写入”，但随后以转折、独立句、新主语或引述声称某内容已经写入正式记录
- **THEN** 系统仍识别并拒绝该正面声称，不用前面的否定覆盖后文

### Requirement: 连续候选改写必须以用户指定的上一版为基准

用户要求对上一版候选调整语气、措辞或精简时，系统 MUST 以经安全保存且已复验的上一版候选为直接改写基准，保留其实质内容、事实关系、必要限定与不确定性。原 Entry 和 Source 仅用于权限/版本复验、溯源和识别来源边界，MUST NOT 无条件取代上一版候选。候选中的模型新增判断 MUST 继续标识为候选内容，不得升格为正式 Entry 或 Source 事实。

#### Scenario: 只改语气不回退到原 Entry

- **WHEN** 上一版候选已经纳入经用户要求保留的限定和模型分析，用户说“内容不变，只换成更简短自然的说法”
- **THEN** 模型输入和确定性校验都以上一版候选为内容基准，允许自然近义改述，但不得遗漏实质限定、改变事实或混淆来源身份

#### Scenario: 失败续接使用同一份安全稿与对应缺口

- **WHEN** 候选改写或 continuation finalizer 的新输出仍未通过校验
- **THEN** 系统不因为“更新”无条件接受该输出，而是保存经内容边界检查的安全稿件及对应的最新缺口
- **AND** 下一次“继续”针对该稿件和真实未完成项只重试最终交付，不重放旧稿或重复资料工具

### Requirement: 候选安全稿与恢复缺口必须原子推进

候选 finalizer 的本轮输出通过候选内容安全边界时，运行状态、编辑上下文与 continuation MUST 使用同一份最新安全稿及其同次校验缺口；输出未通过内容安全边界时 MUST 保留上一安全稿及其对应缺口，不得混配版本。连续恢复得到相同安全稿和相同缺口时，系统 MUST 准确说明本次没有进展，MUST NOT 继续承诺重复“继续”即可修复，也不得为此增加重试或预算。

#### Scenario: 新安全稿替换恢复材料

- **WHEN** continuation finalizer 生成了与上一版不同、通过内容安全边界但仍缺少交付边界的新候选
- **THEN** 当前状态、editing context 和 continuation 同时保存该新稿与本次实际缺口，下一次继续使用新稿

#### Scenario: 不安全输出不覆盖上一安全稿

- **WHEN** continuation finalizer 的新输出包含越权结构、正式写入声称或错误来源归属而未通过内容安全边界
- **THEN** 系统保留上一安全稿及其原配缺口，不把不安全文本写入恢复快照

#### Scenario: 连续恢复没有进展

- **WHEN** 连续两次恢复后的安全稿和缺口均相同
- **THEN** 用户收到明确无进展说明，系统不重复承诺下一次继续可解决，也不重新调用资料工具

### Requirement: 候选纠错与只改表达必须使用不同内容基准

当用户要求按分析纠正或补充内容时，finalizer MUST 允许候选不同于原 Entry，同时明确区分原记录、模型判断、候选和未写入状态；不得以“与原记录冲突”为由强制保留已被用户要求纠正的表达。当用户只要求语气、措辞、精简或润色时，finalizer MUST 以上一安全候选为内容基准，并继续保护事实关系、数量维度和不确定性。程序 MAY 附加候选与尚未写入等确定事实，但 MUST NOT 以尾部免责声明掩盖正文把模型判断冒充 Source 或正式记录的错误归属，也不得依赖持续扩张的同义词表判断来源边界。

#### Scenario: 按分析纠正原记录

- **WHEN** 前轮分析指出原 Entry 将释放限量误写成添加量且安全结论过于绝对，用户要求按分析修改
- **THEN** 候选可纠正这两处内容，并把纠正标识为模型候选判断；提示和校验不得要求继续保留原错误表达

#### Scenario: 只改语气保护上一版内容

- **WHEN** 上一安全候选已完成内容纠正，用户只要求更简短自然
- **THEN** 模型输入和校验以上一安全候选为基准，不能回退原 Entry、删除必要限定或改变来源身份

### Requirement: 正式 Web 必须展示真实 dialogue-loop 阶段

生产适配器 MUST 将统一循环已有 activity callback 的去重阶段通过正式 Run API 暴露给 Grove Web。Web MUST 使用真实阶段显示轻量、可访问的“组织回答中”“查询知识库中”“读取记录中”“核验来源中”或“整理回答中”，不得用定时器推测阶段，不得恢复诊断侧栏。完成、部分完成、失败或取消后 MUST 停止动效；刷新、切换会话及 continuation MUST 只显示当前活动 Run 的当前阶段，并遵守减少动画偏好。

#### Scenario: 正式 Run 推进真实阶段

- **WHEN** 统一循环依次发布 organizing、querying、reading_entries、reading_sources 与 finalizing
- **THEN** 正式 API 和 Web 依次呈现对应用户文案，阶段变化不改写 Worker 恢复用 `current_step`

#### Scenario: 终态和会话切换清理阶段

- **WHEN** Run 进入 completed、partial、failed 或 cancelled，或用户切换到另一会话
- **THEN** 页面停止该 Run 动效且不显示上一会话或上一 Run 的阶段

#### Scenario: 减少动画偏好

- **WHEN** 用户系统启用 `prefers-reduced-motion: reduce`
- **THEN** 阶段文案和可访问状态播报仍可用，旋转或脉冲动效停止

