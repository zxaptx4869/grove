## ADDED Requirements

### Requirement: 候选关联到已有 Entry

确认台 MUST 在候选存在关系建议时展示该建议，并允许用户把候选关联到项目内已有 Entry；疑似重复 MUST 补充来源证据；可以补充或可能冲突 MUST 支持应用修订草稿；关联后候选 MUST 变为已采纳并关联目标 Entry；用户 MUST 仍可选择按新知识创建。

#### Scenario: 疑似重复补充来源

- **WHEN** 候选关系状态为 `duplicate` 且用户选择补充来源证据
- **THEN** 候选证据被补充到目标 Entry，候选变为已采纳并关联目标 Entry

#### Scenario: 可以补充应用修订

- **WHEN** 候选关系状态为 `supplement` 且用户选择应用修订草稿
- **THEN** 目标 Entry 按草稿更新，候选变为已采纳并关联目标 Entry

#### Scenario: 冲突并列保留

- **WHEN** 候选关系状态为 `conflict` 且用户选择并列保留
- **THEN** 系统按新知识创建 Entry，候选变为已采纳

#### Scenario: 仍按新知识创建

- **WHEN** 用户不采纳关系建议而选择按新知识创建
- **THEN** 系统按现有归档流程创建新 Entry，候选变为已采纳
