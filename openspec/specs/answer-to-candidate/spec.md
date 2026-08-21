# answer-to-candidate Specification

## Purpose
TBD - created by archiving change add-reader-agent-with-citations. Update Purpose after archive.
## Requirements
### Requirement: 保存前可编辑
系统 MUST 在用户保存回答时先展示编辑框，允许修改标题与内容后再确认；用户未确认前 MUST NOT 创建任何 Source 或 Candidate。

#### Scenario: 编辑后保存
- **WHEN** 用户在 AI 阅读回答中点击「保存为知识」并修改标题与内容
- **THEN** 使用编辑后的标题与内容创建候选

#### Scenario: 未确认不创建
- **WHEN** 用户取消保存
- **THEN** 不创建任何 Source 或 Candidate

### Requirement: 创建虚拟 Source
系统 MUST 在确认保存后创建「AI 阅读问答」类型的虚拟 Source，归属当前项目与 Workspace；虚拟 Source MUST 记录原始问题与回答文本，作为候选可溯源的上下文。

#### Scenario: 虚拟 Source 承载问答
- **WHEN** 用户确认保存回答
- **THEN** 创建归属当前项目与 Workspace 的虚拟 Source，包含问题与回答原文

#### Scenario: Workspace 隔离
- **WHEN** 保存请求来自其他 Workspace 的项目
- **THEN** 请求失败（404），不创建任何数据

### Requirement: 回答转 Candidate
系统 MUST 把编辑后的回答创建为待采纳 Candidate，归属该虚拟 Source；Candidate 的证据 MUST 引用被引用 Entry 的原始 Source 证据（attachment 与原文片段）；候选进入确认台，等待用户确认后走既有归档流程。

#### Scenario: 候选进入确认台
- **WHEN** 回答保存成功
- **THEN** 创建待采纳 Candidate，证据引用原始 Source 的 attachment 与原文片段

#### Scenario: 不直接写入 Entry
- **WHEN** 回答被保存为候选
- **THEN** 不创建或修改任何正式 Entry，正式归档仍由用户确认后完成

### Requirement: 引用校验
系统 MUST 在保存请求中校验引用的 `entry_id` / `source_id` 属于当前 Workspace 与项目；非法或越权引用 MUST 使请求失败（400），不创建数据。

#### Scenario: 非法引用被拒绝
- **WHEN** 保存请求包含不属于当前项目或 Workspace 的引用
- **THEN** 请求失败（400），不创建任何数据

