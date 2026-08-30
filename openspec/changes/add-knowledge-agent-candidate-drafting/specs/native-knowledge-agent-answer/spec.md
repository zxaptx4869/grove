## ADDED Requirements

### Requirement: 回答后续动作使用结构化协议
原生回答展示 MUST 根据服务端回答状态、最终 citations、source Run 与可用目标项目构造「整理成知识」结构化动作；MUST NOT 通过解析回答正文、固定字符串或模型自报 save_recommended 决定可写状态。动作必须保留来源回答与生成时范围。

#### Scenario: completed 回答提供结构化动作
- **WHEN** 服务端返回 completed 回答、source Run 和有效 citations
- **THEN** 客户端以 source_run_id 发起 draft_candidate，不从正文反推引用或项目

#### Scenario: partial 回答提供受限动作
- **WHEN** 服务端返回 partial 回答且仍有有效 citations
- **THEN** 动作说明只整理有依据部分，未解决 gaps 不进入 Candidate 草稿事实

#### Scenario: 历史回答恢复动作
- **WHEN** 用户重新打开包含可用历史回答的 Conversation
- **THEN** 动作仍锚定该历史 source Run 的范围快照；服务端判定 Evidence 失效时显示可恢复错误而非改用当前回答

### Requirement: 回答、草稿与 Candidate 回执语义分离
原生 App MUST 分别使用「基于正式知识的即时回答」「AI 草稿 · 未创建候选」「已创建待确认知识 · 尚未写入正式知识」表达三类对象；任何 Badge、标题、按钮或 Toast MUST NOT 把 Draft/Candidate 显示为正式 Entry。

#### Scenario: 草稿生成完成
- **WHEN** operation Run 返回 draft 状态
- **THEN** 草稿卡使用 AI 建议语义并提供编辑/确认动作，不使用 confirmed 语义

#### Scenario: Candidate 创建完成
- **WHEN** Draft 确认并关联 pending Candidate
- **THEN** 回执显示待确认状态、来源与目标项目，不显示“正式知识已保存”
