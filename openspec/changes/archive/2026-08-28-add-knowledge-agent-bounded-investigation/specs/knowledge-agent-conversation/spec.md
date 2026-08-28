## MODIFIED Requirements

### Requirement: 对话与消息历史可恢复
系统 MUST 持久化用户消息、助手消息和范围事件，并提供按当前 Workspace 列出对话、按游标分页读取消息及恢复最近活动状态的接口；消息与关联 Run MUST 能返回生成时的上下文模式、实际决策、工作集版本摘要、请求/实际回答模式及可用的调查摘要。

#### Scenario: 重新打开对话
- **WHEN** 客户端重启后读取一个有权限的对话
- **THEN** 系统返回当前范围、活动主题摘要、持久化消息及其关联 Run 状态、上下文决策、回答模式和调查摘要

#### Scenario: 分页读取长对话
- **WHEN** 对话消息超过单页数量且客户端携带游标继续读取
- **THEN** 系统按稳定顺序返回下一页且不重复或跳过消息

#### Scenario: 按 Workspace 列出对话
- **WHEN** 用户列出当前 Workspace 的知识对话
- **THEN** 系统只返回该用户在当前 Workspace 创建的对话并按最近活动时间排序

### Requirement: 用户消息幂等提交
系统 MUST 要求客户端提交稳定的 `client_message_id`，并接受默认 `auto` 的 `context_mode` 与默认 `auto` 的 `answer_mode`；同一对话内重复提交相同标识 MUST 返回首次创建的用户消息、请求模式和 Run，不得按重试载荷改变上下文、回答模式或再次执行问答。

#### Scenario: 首次提交问题
- **WHEN** 用户以新的 `client_message_id`、非空问题、合法上下文模式和合法回答模式向空闲对话提交
- **THEN** 系统在同一事务中创建用户消息、助手占位消息与待执行 Run，并固化两种请求模式和当时的输入工作集版本

#### Scenario: 未提交上下文模式
- **WHEN** 兼容客户端不提供 `context_mode` 或 `answer_mode`
- **THEN** 系统分别按 `auto` 创建 Run

#### Scenario: 网络重试重复提交
- **WHEN** 客户端在同一对话重复提交已使用的 `client_message_id` 且携带不同模式
- **THEN** 系统返回原用户消息和原 Run 且不创建重复记录、不改变首次上下文模式或回答模式

#### Scenario: 空问题不入队
- **WHEN** 用户提交空白问题
- **THEN** 系统拒绝请求且不创建消息或 Run

## ADDED Requirements

### Requirement: 当前 Run 占位消息不进入决策历史
系统 MUST 在上下文决策和调查路由的有限历史中排除当前 Run 的用户消息及其空助手占位消息，并忽略其他无内容助手占位；排除占位后 MUST 仍按上限选取完整、稳定的既有消息历史。

#### Scenario: 真实提交后选择历史
- **WHEN** 消息提交流程已创建当前用户消息和空助手占位后执行上下文决策
- **THEN** 输入历史不包含这两个当前对象，且空占位不会挤掉一条有效既有消息

#### Scenario: 历史中残留空助手消息
- **WHEN** 较早 Run 留有无内容助手占位
- **THEN** 历史选择忽略该消息并继续选取有效历史
