## ADDED Requirements

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

