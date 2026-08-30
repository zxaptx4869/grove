## ADDED Requirements

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
