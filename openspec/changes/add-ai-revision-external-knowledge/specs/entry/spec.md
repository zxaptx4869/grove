## MODIFIED Requirements

### Requirement: AI 修订建议生成与对话调整

系统 MUST 支持用户对单条 Entry 发起 AI 修订建议：生成 MUST 基于该 Entry 的内容与其来源证据，并可结合 AI 自身知识（外部知识）进行求证与补充；AI 输出 MUST 区分「材料/知识库内容」与「AI 知识补充」（回复中以文字标注、草稿以 `external_supplemented` 标记），MUST NOT 编造来源证据；AI 输出 MUST 始终作为候选草稿展示，MUST NOT 直接修改 Entry；对话调整 MUST 是一次性的：每次「继续调整」MUST 携带完整对话历史、当前草稿与用户新指令，且系统 MUST NOT 持久化会话与消息；对话 MUST 区分讨论与提出草稿——用户提问、求证、讨论、质疑时 MUST 只返回文字回复且不产生或更新草稿，只有用户明确要求修改时 MUST 返回草稿，且该选择 MUST 通过显式意图（`intent: discuss | propose`）结构化表达并在响应中返回；模型不可用或调用失败时 MUST 明确标记降级（`is_fallback` 与原因），不得静默降级。

#### Scenario: 发起修订建议
- **WHEN** 用户对某 Entry 点击「AI 修订建议」并生成
- **THEN** 返回候选草稿（含建议字段、修订原因与变更说明），Entry 本身保持不变

#### Scenario: 继续对话调整
- **WHEN** 用户在对话中发送新指令
- **THEN** 模型基于完整对话历史、当前草稿与新指令返回更新后的草稿与自然语言回复

#### Scenario: 结合外部知识补充且可辨识
- **WHEN** 用户要求求证或丰富，且知识库证据不足
- **THEN** AI 可结合自身知识补充，并在回复中文字标注「AI 知识补充」、草稿标记 `external_supplemented=true`，不编造来源证据

#### Scenario: 纯讨论只回复不产草稿
- **WHEN** 用户发送提问、求证、讨论或质疑的消息
- **THEN** 响应 `intent=discuss`，只返回文字回复，不产生也不更新草稿；若已有草稿则保持不变

#### Scenario: 明确要求修改才更新草稿
- **WHEN** 用户明确要求修改（补充、精简、改写法、加条件等）
- **THEN** 响应 `intent=propose` 并返回更新后的完整草稿

#### Scenario: 意图与草稿不一致时归一化
- **WHEN** 模型输出 `intent=discuss` 却携带草稿，或 `intent=propose` 却缺少草稿
- **THEN** 应用层按 `discuss` 处理并记录告警日志，不更新草稿

#### Scenario: 关闭面板即消失
- **WHEN** 用户关闭修订建议面板且未应用
- **THEN** 对话与草稿不落库，Entry 保持不变

#### Scenario: 模型不可用降级可见
- **WHEN** 未配置文本模型密钥或模型调用失败
- **THEN** 响应标记 `is_fallback=true` 并返回降级原因，不生成草稿，且记录告警日志

### Requirement: 应用 AI 修订建议

系统 MUST 支持用户在确认后应用 AI 修订草稿：应用 MUST 按用户确认后的字段更新 Entry、创建「AI 修订建议」虚拟 Source（记录用户指令、AI 输出与 provider/model）并加入 Entry 来源证据、追加一条 `ai_revision` 类型版本并记录变更说明；原有来源证据 MUST 保持不变；未应用时 Entry MUST 保持不变；越权 Entry MUST 请求失败（404）。

#### Scenario: 应用草稿成功并沉淀虚拟来源
- **WHEN** 用户确认并应用 AI 修订草稿
- **THEN** Entry 按确认后的字段更新，来源证据新增「AI 修订建议」虚拟 Source（可打开查看指令与 AI 输出），并追加 `ai_revision` 版本带变更说明，原有来源证据不变

#### Scenario: 未应用保持不变
- **WHEN** 用户放弃或关闭修订建议面板
- **THEN** Entry 内容、来源与版本均不发生变化

#### Scenario: 越权 Entry 不可应用
- **WHEN** 应用请求的 Entry 不属于当前 Workspace
- **THEN** 请求失败（404），不修改任何数据
