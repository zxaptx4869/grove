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
系统 MUST 在范围变更时记录范围事件、更新对话当前范围并关闭当前活动工作集；已有消息、Run 与工作集版本 MUST 保留生成时的范围快照，不得因后续范围切换而改变或在新范围自动复用。

#### Scenario: 空闲对话切换范围
- **WHEN** 用户在没有活动 Run 的对话中从 Workspace 切换到某个项目
- **THEN** 系统原子更新当前范围、关闭活动工作集并追加包含前后范围标签的 `scope_change` 系统消息

#### Scenario: 活动 Run 期间切换范围
- **WHEN** 对话存在 `waiting` 或 `processing` Run 且用户请求切换范围
- **THEN** 系统返回冲突响应且保持原范围与活动工作集不变

#### Scenario: 查看历史消息范围
- **WHEN** 用户切换范围后读取切换前的消息、Run 与工作集版本
- **THEN** 系统仍返回它们生成时的 Workspace 或项目范围快照，但不将旧工作集用于新范围

### Requirement: 对话与消息历史可恢复
系统 MUST 持久化用户消息、助手消息和范围事件，并提供按当前 Workspace 列出对话、按游标分页读取消息及恢复最近活动状态的接口；消息与关联 Run MUST 能返回生成时的上下文模式、实际决策和工作集版本摘要。

#### Scenario: 重新打开对话
- **WHEN** 客户端重启后读取一个有权限的对话
- **THEN** 系统返回当前范围、活动主题摘要、持久化消息及其关联 Run 状态和上下文决策

#### Scenario: 分页读取长对话
- **WHEN** 对话消息超过单页数量且客户端携带游标继续读取
- **THEN** 系统按稳定顺序返回下一页且不重复或跳过消息

#### Scenario: 按 Workspace 列出对话
- **WHEN** 用户列出当前 Workspace 的知识对话
- **THEN** 系统只返回该用户在当前 Workspace 创建的对话并按最近活动时间排序

### Requirement: 用户消息幂等提交
系统 MUST 要求客户端提交稳定的 `client_message_id`，并接受默认 `auto` 的 `context_mode`；同一对话内重复提交相同标识 MUST 返回首次创建的用户消息、请求模式和 Run，不得按重试载荷改变上下文或再次执行问答。

#### Scenario: 首次提交问题
- **WHEN** 用户以新的 `client_message_id`、非空问题和合法上下文模式向空闲对话提交
- **THEN** 系统在同一事务中创建用户消息、助手占位消息与待执行 Run，并固化请求模式和当时的输入工作集版本

#### Scenario: 未提交上下文模式
- **WHEN** 兼容客户端不提供 `context_mode`
- **THEN** 系统按 `auto` 创建 Run

#### Scenario: 网络重试重复提交
- **WHEN** 客户端在同一对话重复提交已使用的 `client_message_id`
- **THEN** 系统返回原用户消息和原 Run 且不创建重复记录、不改变首次上下文模式

#### Scenario: 空问题不入队
- **WHEN** 用户提交空白问题
- **THEN** 系统拒绝请求且不创建消息或 Run

