## ADDED Requirements

### Requirement: Knowledge Agent 单 Entry 修订复用正式版本服务
系统 MUST 允许用户确认后的 Knowledge Agent Revision Draft 通过应用服务更新一条正式 Entry；更新 MUST 复用 Entry 字段校验、版本快照、来源 Evidence、Project Context 刷新与 embedding 更新机制，并以明确 change type/summary 标识 Knowledge Agent 修订。AI 草稿未确认时 MUST NOT 修改 Entry。

#### Scenario: 应用 Knowledge Agent 修订
- **WHEN** 用户确认基线和 Evidence 仍有效的单 Entry Revision Draft
- **THEN** Entry 按确认字段更新、追加修订版本、保留既有来源并补充去重来源

#### Scenario: 无实际字段变化
- **WHEN** 确认载荷归一化后与当前 Entry 完全一致
- **THEN** 系统不追加空版本、不创建 Execution 成功结果，并返回稳定冲突

#### Scenario: 现有桌面修订兼容
- **WHEN** 用户继续使用桌面人工编辑、AI 修订建议、Candidate 修订或版本恢复
- **THEN** 既有外部知识、版本类型、来源与响应语义保持不变，不要求经过 Knowledge Conversation

### Requirement: 操作撤销不覆盖后续 Entry 版本
系统 MUST 为 Knowledge Agent 修订保存操作前后快照与版本关联；本操作撤销 MUST 在 Entry 未发生后续修改时追加恢复版本，MUST NOT 删除版本历史。若最新版本或当前字段已变化，系统 MUST 拒绝自动撤销。

#### Scenario: 未发生后续修改时撤销
- **WHEN** Knowledge Agent 修订仍是 Entry 最新变化且 after snapshot 匹配
- **THEN** 系统恢复 before snapshot、追加 restored 版本并保留 applied/undo 审计

#### Scenario: 后续版本阻止撤销
- **WHEN** Entry 在该修订后又被编辑、移动、修订或恢复
- **THEN** 系统返回 409 且不改变 Entry 或版本历史

### Requirement: 撤销只移除本操作新增的来源 Evidence
系统 MUST 在 Knowledge Agent 修订 Execution 中记录实际新增的 EntrySourceEvidence 关系；撤销成功时只删除这些仍属于 target Entry 的关系，MUST NOT 删除操作前已有、等价复用或其他操作新增的 Evidence。

#### Scenario: 修订新增一个来源后撤销
- **WHEN** applied Execution 新增了一条 Evidence 且之后未发生冲突变化
- **THEN** 撤销删除该条关系并保留 Entry 的所有既有 Evidence

#### Scenario: 采用的 Evidence 原本已关联
- **WHEN** 修订采用的 Source/Attachment/quote 在操作前已属于 Entry
- **THEN** Execution 不把该关系记录为新增，撤销时不会删除它
