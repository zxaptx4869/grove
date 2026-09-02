## MODIFIED Requirements

### Requirement: 用户可覆盖上下文与回答模式
原生 App MUST 默认按 `context_mode=auto`、`answer_mode=auto`、`result_mode=auto` 与 `basis_mode=auto` 提交，并提供下一条消息的一次性覆盖：继续当前主题、新话题、快速回答、深度查找、综合回答、列出知识和仅使用我的知识库。非默认选择 MUST 在发送前可见、可移除，成功提交后 MUST 恢复默认；提交结果未知的重试 MUST 复用原选择和同一 `client_message_id`。

#### Scenario: 默认自动模式
- **WHEN** 用户不打开模式设置直接发送
- **THEN** 客户端提交四种 `auto` 且不在输入区堆叠模式标签

#### Scenario: 强制深度查找
- **WHEN** 用户选择深度查找后发送下一条消息
- **THEN** 客户端提交 `answer_mode=investigate`，发送前显示该选择，成功后下一条恢复 auto

#### Scenario: 仅使用我的知识库
- **WHEN** 用户为下一条消息选择“仅使用我的知识库”
- **THEN** Composer 显示可移除的一次性依据 Chip，提交 `basis_mode=knowledge_only`，成功后下一条恢复 auto

#### Scenario: 强制继续当前主题
- **WHEN** 用户认为自动判断错误并为下一条选择继续当前主题
- **THEN** 客户端提交 `context_mode=continue`，保留服务端可能要求澄清的结果

#### Scenario: 强制新话题
- **WHEN** 用户为下一条选择新话题
- **THEN** 客户端提交 `context_mode=new_topic`，并在成功后清除该一次性覆盖

#### Scenario: 依据模式网络重试
- **WHEN** `knowledge_only` 消息提交结果未知
- **THEN** 客户端保留原 Conversation、文本、四类模式和 `client_message_id` 重试，不改回 auto 或创建第二条本地消息

#### Scenario: 旧服务端缺少依据能力
- **WHEN** 原生 App 收到不包含 basis 字段的旧响应或服务端明确不接受新字段
- **THEN** 已有对话、回答、范围、上下文和回答模式继续可用，界面不伪造依据记录
