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

