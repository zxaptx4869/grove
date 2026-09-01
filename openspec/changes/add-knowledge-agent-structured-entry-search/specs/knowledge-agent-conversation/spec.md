## MODIFIED Requirements

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
系统 MUST 要求客户端提交稳定的 `client_message_id`，并接受默认 `auto` 的 `context_mode`、默认 `auto` 的 `result_mode` 与默认 `auto` 的 `answer_mode`；同一对话内重复提交相同标识 MUST 返回首次创建的用户消息、请求模式和 Run，不得按重试载荷改变上下文、结果形态、回答模式或再次执行路由与问答。

#### Scenario: 首次提交问题
- **WHEN** 用户以新的 `client_message_id`、非空问题、合法上下文模式、合法结果形态和合法回答模式向空闲对话提交
- **THEN** 系统在同一事务中创建用户消息、助手占位消息与待执行 Run，并固化三种请求模式和当时的输入工作集版本

#### Scenario: 未提交模式
- **WHEN** 兼容客户端不提供 `context_mode`、`result_mode` 或 `answer_mode`
- **THEN** 系统分别按 `auto` 创建 Run

#### Scenario: 网络重试重复提交
- **WHEN** 客户端在同一对话重复提交已使用的 `client_message_id` 且携带不同模式
- **THEN** 系统返回原用户消息和原 Run，且不创建重复记录、不改变首次上下文模式、结果形态或回答模式

#### Scenario: 空问题不入队
- **WHEN** 用户提交空白问题
- **THEN** 系统拒绝请求且不创建消息或 Run
