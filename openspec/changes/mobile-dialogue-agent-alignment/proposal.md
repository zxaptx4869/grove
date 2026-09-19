## Why

原生 App 的知识对话仍围绕旧 `answer/citations`、Candidate Draft 和 Entry Revision 合同实现，而正式 Knowledge Agent 已统一通过 `dialogue_loop_status`、`dialogue_stage`、`dialogue_blocks` 与 `can_continue` 交付结果。继续在旧模块叠加兼容会让同一对话同时存在两套状态、依据语义和恢复路径，因此需要在移动端尚未上线时完成一次有边界的替换。

## What Changes

- **BREAKING**：原生 App 只保留一套正式 Agent 对话实现，以服务端 `dialogue_*` 字段和块顺序为主合同；旧扁平回答只作为缺少结构化结果时的简单历史回退。
- 原生端展示 text、list、statistic、entry、evidence、candidate、insufficient 等正式块，安全处理未知块，并避免与完整扁平答案重复。
- 知识列表中的明确 Entry 项支持原位按需读取当前正文、收起、失败重试和不可访问状态；读取仅是客户端查看，不写入 Agent 上下文、不发送消息、不调用模型。
- 原生端使用真实阶段和终态，按当前 Conversation 的服务端 `can_continue` 提供正式续接；继续、提交结果未知重试与失败后重新提问使用不同的消息和幂等语义。
- **BREAKING**：移除原生端快速/深度、强制结果形式、依据模式、旧结果纠正、固定“整理成知识”、Candidate Draft、Entry Revision、末尾旧引用条及其专用状态、组件、API 和测试。
- 普通对话中的 candidate 块仅显示为“修改建议/候选稿，未应用”，不创建持久 Draft，也不提供知识写操作。
- 保留 Expo 工程、路由与底部导航、认证与安全存储、基础网络、主题和基础 UI、会话历史与分页、知识范围、幂等提交、前台轮询、取消和服务端恢复。
- 不修改共享 dialogue loop、提示词、工具边界、Candidate/Revision 后端服务或数据库数据；不实现收集、待处理、知识主页面。

## Capabilities

### New Capabilities

- 无。

### Modified Capabilities

- `native-knowledge-agent-conversation`：收敛提问设置，增加正式 dialogue 状态、continuation、恢复与三类重试语义，删除旧模式覆盖要求。
- `native-knowledge-agent-answer`：以正式 dialogue blocks 展示回答与真实依据，移除旧 citations、Candidate Draft、Entry Revision 和复杂旧回答合同。
- `native-knowledge-agent-entry-results`：将正式块中的知识列表按服务端原序展示，并支持明确 Entry 的当前正文按需原位展开。
- `native-knowledge-agent-candidate-draft`：移除原生端持久 Candidate Draft 创建、编辑、确认、取消、重试和回执能力。
- `native-knowledge-agent-entry-revision`：移除原生端 Entry Revision 发起、编辑、差异确认、应用、撤销和回执能力。

## Impact

- 主要影响 `mobile/src/knowledge-agent/` 的类型、API、状态控制器、回答/过程/列表组件及相关测试。
- 原生端不再调用知识 Candidate Draft 与 Entry Revision 写接口；共享后端端点、应用服务和 Web 调用方保持不变。
- 不新增数据库迁移、依赖、模型调用或 Agent 编排阶段。
- 当前正式对话历史继续由服务端 Conversation、Message、Run 和 dialogue 快照恢复；测试期旧草稿、旧候选和修订交互不做迁移。
