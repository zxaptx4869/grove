## ADDED Requirements

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
