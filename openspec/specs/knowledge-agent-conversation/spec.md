# knowledge-agent-conversation Specification

## Purpose
Workspace 内知识对话、消息与范围事件：按用户与 Workspace 隔离，范围只支持全部知识与具体项目，支持幂等提交、历史恢复与游标分页。
## Requirements
### Requirement: 对话所有权与 Workspace 隔离
系统 MUST 将知识对话永久归属到创建时的 Workspace 和当前用户；对话、消息和 Run 的所有读写 MUST 同时校验当前用户与 Workspace，不得向其他用户或 Workspace 暴露对象是否存在。

#### Scenario: 创建当前 Workspace 对话
- **WHEN** 已认证用户在当前 Workspace 创建知识对话
- **THEN** 系统保存该 Workspace 与用户为对话归属并返回对话

#### Scenario: 访问其他 Workspace 对话
- **WHEN** 用户读取或修改不属于当前 Workspace 的对话
- **THEN** 系统返回 404 且不返回对话、消息或 Run 数据

#### Scenario: 访问同 Workspace 其他用户的对话
- **WHEN** 用户读取或修改同一 Workspace 内由其他用户创建的对话
- **THEN** 系统返回 404 且不暴露对话是否存在

### Requirement: 对话范围只支持 Workspace 与项目
系统 MUST 允许知识对话选择当前 Workspace「全部知识」或当前 Workspace 内一个项目作为范围；系统 MUST NOT 向用户提供目录节点级问答范围。

#### Scenario: 创建 Workspace 范围对话
- **WHEN** 用户以「全部知识」创建对话
- **THEN** 系统将当前 Workspace 保存为对话范围且 `project_id` 为空

#### Scenario: 创建项目范围对话
- **WHEN** 用户选择当前 Workspace 内的项目创建对话
- **THEN** 系统将该项目保存为对话当前范围

#### Scenario: 选择越权项目
- **WHEN** 用户创建对话或切换范围时提交不属于当前 Workspace 的项目
- **THEN** 系统返回 404 且不改变对话范围

#### Scenario: 提交节点范围
- **WHEN** 客户端尝试将目录节点作为知识对话范围提交
- **THEN** 系统拒绝该范围且不创建节点级范围状态

### Requirement: 范围变更可见且历史范围稳定
系统 MUST 在实际范围变更时记录范围事件、更新对话当前范围并关闭当前活动工作集；已有消息、Run 与工作集版本 MUST 保留生成时的范围快照，不得因后续范围切换而改变或在新范围自动复用。提交与当前 scope_type/project_id 相同的范围 MUST 幂等返回当前对话，不关闭工作集或新增系统消息。

#### Scenario: 空闲对话切换范围
- **WHEN** 用户在没有活动 Run 的对话中从 Workspace 切换到某个项目
- **THEN** 系统原子更新当前范围、关闭活动工作集并追加包含前后范围标签的 `scope_change` 系统消息

#### Scenario: 切换到相同范围
- **WHEN** 用户提交与对话当前 Workspace 或项目完全相同的范围
- **THEN** 系统返回当前对话且不关闭工作集、不改变最近活动时间、不追加 `scope_change`

#### Scenario: 活动 Run 期间切换范围
- **WHEN** 对话存在 `waiting` 或 `processing` Run 且用户请求切换到不同范围
- **THEN** 系统返回冲突响应且保持原范围与活动工作集不变

#### Scenario: 查看历史消息范围
- **WHEN** 用户切换范围后读取切换前的消息、Run 与工作集版本
- **THEN** 系统仍返回它们生成时的 Workspace 或项目范围快照，但不将旧工作集用于新范围

### Requirement: 对话与消息历史可恢复
系统 MUST 持久化用户消息、助手消息和范围事件，并提供按当前 Workspace 列出对话、按不透明游标读取最近消息与向前加载更早消息、恢复最近活动状态的接口；对话摘要 MUST 批量返回最近 Run 的 id/status/current_step/updated_at，消息页 MUST 规范化返回当前页关联的去重 Run；消息与 Run MUST 能返回生成时的上下文模式、请求/实际结果形态、实际决策、工作集版本摘要、请求/实际回答模式、结构化回答或结构化 Entry 首屏结果及可用调查摘要。

#### Scenario: 重新打开对话
- **WHEN** 客户端重启后读取一个有权限的对话
- **THEN** 系统返回当前范围、活动主题摘要、最近一页持久化消息、关联 Run 状态、请求/实际结果形态、综合回答或 Entry 首屏结果、上下文决策、回答模式和调查摘要

#### Scenario: 初次读取长对话
- **WHEN** 对话消息超过单页数量且客户端不携带游标
- **THEN** 系统选择最新一页消息、按时间正序返回，并给出可加载更早消息的游标

#### Scenario: 向前分页读取历史
- **WHEN** 客户端携带上一页返回的更早游标
- **THEN** 系统返回紧邻的更早一页且页内正序，不重复或跳过消息与关联 Run

#### Scenario: 分页读取长对话
- **WHEN** 对话消息超过单页数量且客户端携带服务端返回的不透明游标继续读取
- **THEN** 系统按稳定的向前分页语义返回更早一页且不重复或跳过消息

#### Scenario: 消息页规范化返回 Run
- **WHEN** 一页中用户消息和助手消息关联同一 Run
- **THEN** `items` 保留 run_id，`runs` 集合只返回该 Run 一次并包含状态、请求/实际结果形态、对应终态结果和调查摘要

#### Scenario: 按 Workspace 列出对话
- **WHEN** 用户列出当前 Workspace 的知识对话
- **THEN** 系统只返回该用户创建的对话并按最近活动排序，同时用批量查询附最近 Run 摘要，不产生逐对话 N+1

### Requirement: 用户消息幂等提交
系统 MUST 要求客户端提交稳定的 `client_message_id`，并接受默认 `auto` 的 `context_mode`、默认 `auto` 的 `result_mode` 与默认 `auto` 的 `answer_mode`；同一对话内重复提交相同标识 MUST 返回首次创建的用户消息、请求模式和 Run，不得按重试载荷改变上下文、结果形态、回答模式或再次执行路由与问答。模式纠正可额外提交同 Conversation 的 `source_run_id` 与相反的显式结果形态；服务端 MUST 校验来源归属并以来源 Run 的原用户消息、已固化独立问题与上下文决策、范围、上下文模式和输入工作集创建新 Run，不信任客户端重传这些字段。

#### Scenario: 首次提交问题
- **WHEN** 用户以新的 `client_message_id`、非空问题、合法上下文模式、合法结果形态和合法回答模式向空闲对话提交
- **THEN** 系统在同一事务中创建用户消息、助手占位消息与待执行 Run，并固化三种请求模式和当时的输入工作集版本

#### Scenario: 未提交上下文模式
- **WHEN** 兼容客户端不提供 `context_mode`、`result_mode` 或 `answer_mode`
- **THEN** 系统分别按 `auto` 创建 Run

#### Scenario: 网络重试重复提交
- **WHEN** 客户端在同一对话重复提交已使用的 `client_message_id` 且携带不同模式
- **THEN** 系统返回原用户消息和原 Run，且不创建重复记录、不改变首次上下文模式、结果形态或回答模式

#### Scenario: 按来源 Run 纠正结果形态
- **WHEN** 客户端以新 `client_message_id`、同 Conversation 的终态 answer Run 和相反显式 `result_mode` 提交模式纠正
- **THEN** 系统从来源 Run 恢复原消息、独立问题、上下文决策、范围快照、上下文模式与输入工作集，创建独立新 Run，且提交时不提前关闭当前活动工作集

#### Scenario: 空问题不入队
- **WHEN** 用户提交空白问题
- **THEN** 系统拒绝请求且不创建消息或 Run

### Requirement: 当前 Run 占位消息不进入决策历史
系统 MUST 在上下文决策和调查路由的有限历史中排除当前 Run 的用户消息及其空助手占位消息，并忽略其他无内容助手占位；排除占位后 MUST 仍按上限选取完整、稳定的既有消息历史。

#### Scenario: 真实提交后选择历史
- **WHEN** 消息提交流程已创建当前用户消息和空助手占位后执行上下文决策
- **THEN** 输入历史不包含这两个当前对象，且空占位不会挤掉一条有效既有消息

#### Scenario: 历史中残留空助手消息
- **WHEN** 较早 Run 留有无内容助手占位
- **THEN** 历史选择忽略该消息并继续选取有效历史

### Requirement: 对话历史关联候选草稿操作
系统 MUST 将显式候选草稿请求保存为同一 Conversation 内的可见用户消息，并把关联 operation Run 与 Candidate Draft 规范化返回；所有读取与提交 MUST 同时校验 owner、Workspace 和 Conversation。普通问答消息保持既有 answer 语义。

#### Scenario: 保存候选草稿请求消息
- **WHEN** 用户在空闲 Conversation 对一条本会话回答提交 draft_candidate 动作
- **THEN** 系统在同一事务创建可见用户消息、助手占位、operation Run 与 generating Draft，并固化 source_run_id 和目标项目

#### Scenario: 消息页关联 Draft
- **WHEN** 一页消息包含候选草稿 operation Run
- **THEN** `items` 保留 run_id，规范化 Draft 集合只返回该 Draft 一次并包含当前状态和 confirmed_candidate_id

#### Scenario: 普通消息保持只读
- **WHEN** 客户端未提交 draft_candidate 动作字段
- **THEN** 系统继续创建 answer Run，不因消息文本自动创建 Draft

#### Scenario: 活动 Run 期间提交草稿动作
- **WHEN** Conversation 已有 waiting 或 processing Run
- **THEN** 系统返回 409 且不创建第二个活动 Run、消息或 Draft

### Requirement: 对话消息承载显式 Entry 修订动作
Knowledge Conversation MUST 支持 `revise_entry` 结构化用户请求并持久化 source Run、target Entry、指令和关联 operation Run；该消息 MUST 对用户可见且与普通 answer、draft_candidate 请求可区分。服务端 MUST 按 owner + Workspace + Conversation 校验全部引用对象。

#### Scenario: 修订动作消息持久化
- **WHEN** 用户提交合法 revise_entry 请求
- **THEN** 系统创建一条可见用户消息和一个关联 entry_revision Run，历史重开保持目标与指令

#### Scenario: 与其他请求争用活动槽
- **WHEN** 同一 Conversation 已存在 waiting/processing 的 answer、draft_candidate 或 entry_revision Run
- **THEN** 新修订请求返回稳定冲突，不创建第二个活动 Run 或孤立 Draft

### Requirement: 消息分页规范化返回 Entry Revision Draft
Conversation 消息页 MUST 批量返回当前页 operation Run 关联的规范化 `entry_revision_drafts` 与 Execution 摘要；分页不得重复或遗漏，且 MUST NOT 把受保护 Evidence、内部基线快照或其他用户草稿暴露给客户端。

#### Scenario: 历史页包含修订操作
- **WHEN** 当前消息页包含 entry_revision operation Run
- **THEN** 响应返回该 Run 关联 Draft 的可展示字段、diff、状态与回执，客户端可恢复真实界面

#### Scenario: 普通历史页不受影响
- **WHEN** 消息页只包含 answer 或 draft_candidate Run
- **THEN** 既有消息、回答、Candidate Draft、调查与分页协议保持不变，entry_revision_drafts 为空集合

### Requirement: 用户消息幂等携带一次性依据覆盖
系统 MUST 接受 `auto` 与 `knowledge_only` 两种请求依据模式，并将其与用户消息、Run 和同一 `client_message_id` 的幂等提交绑定；请求结果未知时重试 MUST 返回首次创建的消息与 Run，不得因重试时的不同参数改变已经固化的依据限制。新客户端 MUST 显式提交该字段；未提交该字段的旧客户端 MUST 按兼容的 `knowledge_only` 行为处理。

#### Scenario: 新客户端默认自动依据
- **WHEN** 支持开放讨论的新客户端显式提交 `basis_mode=auto`
- **THEN** 系统按 `auto` 创建 Run 并允许执行依据规划

#### Scenario: 旧客户端缺少依据字段
- **WHEN** 旧客户端提交问题但不包含 basis mode
- **THEN** 系统按兼容的 `knowledge_only` 行为创建 Run，不向无法展示 basis 的客户端意外开放模型通用回答

#### Scenario: 显式仅使用我的知识
- **WHEN** 客户端以新的 `client_message_id` 提交 `basis_mode=knowledge_only`
- **THEN** 系统在 Run 上固化该限制并立即返回 waiting 状态

#### Scenario: 网络未知后同标识重试
- **WHEN** 首次 `knowledge_only` 提交可能成功但客户端未收到响应，随后使用同一 `client_message_id` 重试
- **THEN** 系统返回首次消息与 Run，不创建第二个 Run且不放宽首次依据限制

#### Scenario: 同标识篡改依据模式
- **WHEN** 已成功的 `client_message_id` 被再次提交且 basis mode 与首次不同
- **THEN** 系统仍返回首次 Run 的固化模式，不更新原消息、规划或执行结果

### Requirement: 历史恢复返回生成时依据而不改写旧回答
Conversation 消息页和 Run 查询 MUST 返回每条 answer Run 生成时的请求依据模式、规划策略与实际回答依据；范围切换、后续消息或重新打开 App MUST NOT 用当前范围或当前模式改写旧回答依据。旧 Run 缺少依据字段时 MUST 保留为空并继续返回原回答、Citation 和降级摘要。

#### Scenario: 恢复混合依据回答
- **WHEN** 用户重新打开包含混合依据回答的 Conversation
- **THEN** 消息页关联 Run 返回原用户陈述消息 ID、Grove Citation 计数、模型知识标记和生成时范围

#### Scenario: 范围切换后查看旧回答
- **WHEN** Conversation 切换项目后读取切换前的回答
- **THEN** 旧回答仍显示生成时的范围与依据，不把新范围知识或陈述计入旧 basis

#### Scenario: 恢复旧版回答
- **WHEN** 历史 answer Run 没有任何 basis 字段
- **THEN** API 返回可空依据且客户端继续按旧响应语义展示，不推断该回答使用过用户陈述或模型通用知识

