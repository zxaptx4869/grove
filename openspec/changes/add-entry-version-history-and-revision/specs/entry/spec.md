## ADDED Requirements

### Requirement: Entry 基础版本历史

系统 MUST 为每条 Entry 维护基础版本历史：创建 Entry 时生成版本 1；每次修改（人工编辑字段或移动目录、应用候选修订草稿、应用 AI 修订建议、从历史恢复）MUST 追加一个版本快照；版本快照 MUST 记录标题、核心内容、主类型、信息性质、适用条件、补充说明与主目录节点；来源证据的增删 MUST NOT 产生版本；每个 Entry 只保留最近 N 条版本（N 默认 10），超出 MUST 滚动丢弃最旧版本。

#### Scenario: 创建生成初始版本
- **WHEN** 用户归档候选创建 Entry
- **THEN** 系统为 Entry 生成版本 1，快照为该 Entry 的初始字段

#### Scenario: 编辑追加快照
- **WHEN** 用户编辑 Entry 字段或移动主目录节点
- **THEN** 系统追加一个版本快照，内容为修改后的字段与主目录节点

#### Scenario: 无实际变化不追加
- **WHEN** 用户提交的编辑没有改变任何字段或主目录节点
- **THEN** 系统不产生新版本

#### Scenario: 应用修订追加版本
- **WHEN** 用户应用候选修订草稿或 AI 修订建议
- **THEN** 系统追加一个版本快照，并记录变更类型与变更说明

#### Scenario: 证据变更不产生版本
- **WHEN** 用户为 Entry 补充来源证据
- **THEN** Entry 字段不变，且不产生新版本

#### Scenario: 超出保留上限滚动丢弃
- **WHEN** Entry 的版本数超过保留上限 N
- **THEN** 系统丢弃最旧版本，只保留最近 N 条

### Requirement: 版本查看与恢复

系统 MUST 提供 Entry 版本列表读取，返回每个保留版本的完整快照字段（含字段值、主目录节点、变更类型、变更说明与创建时间）；读取 MUST 校验 Entry 属于当前 Workspace；用户 SHALL 能把 Entry 恢复到任一保留版本；恢复 MUST 把字段与主目录节点恢复为该版本快照、追加一条「恢复」类型版本，并 MUST NOT 删除后续历史；恢复后 Entry 的 `updated_at` MUST 更新。

#### Scenario: 版本列表按版本号倒序
- **WHEN** 用户读取某 Entry 的版本列表
- **THEN** 返回该 Entry 全部保留版本，按版本号从新到旧排序，每条包含完整快照字段

#### Scenario: 恢复到旧版本
- **WHEN** 用户把 Entry 恢复到某个保留版本
- **THEN** Entry 的字段与主目录节点恢复为该版本快照，并追加一条「恢复」版本，后续历史保持不变

#### Scenario: 越权 Entry 404
- **WHEN** 用户请求的 Entry 不属于当前 Workspace
- **THEN** 请求失败（404），不暴露任何版本数据

#### Scenario: 恢复超出保留范围的版本失败
- **WHEN** 用户请求恢复的版本已被滚动丢弃或不存在
- **THEN** 请求失败（404），Entry 保持不变

### Requirement: AI 修订建议生成与对话调整

系统 MUST 支持用户对单条 Entry 发起 AI 修订建议：生成 MUST 基于该 Entry 的内容与其来源证据，并结合用户可选指令，返回结构化修订草稿（建议字段值、修订原因与变更说明）；AI 输出 MUST 始终作为候选草稿展示，MUST NOT 直接修改 Entry；对话调整 MUST 是一次性的：每次「继续调整」MUST 携带完整对话历史、当前草稿与用户新指令，且系统 MUST NOT 持久化会话与消息；模型不可用或调用失败时 MUST 明确标记降级（`is_fallback` 与原因），不得静默降级。

#### Scenario: 发起修订建议
- **WHEN** 用户对某 Entry 点击「AI 修订建议」并生成
- **THEN** 返回候选草稿（含建议字段、修订原因与变更说明），Entry 本身保持不变

#### Scenario: 继续对话调整
- **WHEN** 用户在对话中发送新指令
- **THEN** 模型基于完整对话历史、当前草稿与新指令返回更新后的草稿与自然语言回复

#### Scenario: 关闭面板即消失
- **WHEN** 用户关闭修订建议面板且未应用
- **THEN** 对话与草稿不落库，Entry 保持不变

#### Scenario: 模型不可用降级可见
- **WHEN** 未配置文本模型密钥或模型调用失败
- **THEN** 响应标记 `is_fallback=true` 并返回降级原因，不生成草稿，且记录告警日志

### Requirement: 应用 AI 修订建议

系统 MUST 支持用户在确认后应用 AI 修订草稿：应用 MUST 按用户确认后的字段更新 Entry、追加一条 `ai_revision` 类型版本并记录变更说明；应用 MUST NOT 修改来源证据；未应用时 Entry MUST 保持不变；越权 Entry MUST 请求失败（404）。

#### Scenario: 应用草稿成功
- **WHEN** 用户确认并应用 AI 修订草稿
- **THEN** Entry 按确认后的字段更新，追加一条 `ai_revision` 版本并带变更说明，来源证据不变

#### Scenario: 未应用保持不变
- **WHEN** 用户放弃或关闭修订建议面板
- **THEN** Entry 内容与版本均不发生变化

#### Scenario: 越权 Entry 不可应用
- **WHEN** 应用请求的 Entry 不属于当前 Workspace
- **THEN** 请求失败（404），不修改任何数据
