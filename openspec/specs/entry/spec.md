# entry Specification

## Purpose
TBD - created by archiving change add-entry-and-provenance. Update Purpose after archive.
## Requirements
### Requirement: Entry 归属与主目录
系统 MUST 提供 `Entry` 模型并归属一个 Project；Entry MUST 有一个主目录节点，且该节点 MUST 属于同一 Project；跨 Workspace 的 Entry MUST 不可见。

#### Scenario: 创建 Entry
- **WHEN** 用户采纳候选并选择项目内目录节点
- **THEN** 创建 Entry，归属当前项目并指向所选主目录节点

#### Scenario: 拒绝跨项目节点
- **WHEN** 归档时选择的节点不属于当前项目
- **THEN** 请求失败，不创建 Entry

### Requirement: Entry 结构化字段
Entry MUST 包含标题、核心内容、主类型、信息性质、适用条件与补充说明；主类型 MUST 为知识、方法、参数或提醒之一。

#### Scenario: 从候选继承字段
- **WHEN** 候选归档为 Entry
- **THEN** Entry 的标题、核心内容、主类型、信息性质、适用条件与补充说明来自候选

### Requirement: Entry 来源证据
系统 MUST 提供 `EntrySourceEvidence` 记录 Entry 与 Source/Attachment 的证据关系；归档时 MUST 把候选证据引用转换为 Entry 证据。

#### Scenario: 证据可追溯
- **WHEN** 候选归档为 Entry
- **THEN** 每条候选证据引用生成一条 EntrySourceEvidence，包含 source_id、attachment_id 与 quote

### Requirement: 采纳并归档
系统 MUST 在用户选择目录后原子创建 Entry，并把 Candidate 关联到 Entry；归档成功后 Candidate MUST 不再允许重新打开。

#### Scenario: 原子归档
- **WHEN** 用户选择目录并采纳候选
- **THEN** Entry 与证据关系创建成功，Candidate 关联 Entry 并变为已采纳

#### Scenario: 归档后锁定候选
- **WHEN** 候选已归档为 Entry
- **THEN** 该候选不能重新打开为待采纳

### Requirement: Entry 编辑与移动
用户 SHALL 能编辑 Entry 的标题、核心内容、主类型、信息性质、适用条件、补充说明与主目录节点；移动目录 MUST 仅限同一 Project；修改 MUST 更新 `updated_at`。

#### Scenario: 编辑 Entry
- **WHEN** 用户修改 Entry 字段
- **THEN** 修改被持久化且 `updated_at` 更新

#### Scenario: 移动 Entry 目录
- **WHEN** 用户把 Entry 移动到同一项目内的其他节点
- **THEN** Entry 主目录节点更新，来源证据保持不变

### Requirement: Entry 来源标题展示
系统 MUST 在 Entry 证据输出中返回来源标题（`source_title`），其值来自证据所指向 Source 的标题；该字段用于卡片与列表的来源展示，不改变证据关系本身。

#### Scenario: 证据含来源标题
- **WHEN** 用户读取一条 Entry 及其证据
- **THEN** 每条证据返回 `source_id`、`attachment_id`、`quote` 与 `source_title`

### Requirement: Entry 按目录浏览
系统 MUST 支持按目录节点读取 Entry，并区分「仅本节点」与「仅后代」两种范围；「仅后代」MUST 只包含该节点严格后代节点的直接 Entry，不含该节点自身；结果 MUST 按创建时间倒序返回；读取 MUST 校验项目属于当前 Workspace。

#### Scenario: 仅本节点
- **WHEN** 用户以「仅本节点」范围读取某节点的 Entry
- **THEN** 只返回主目录为该节点的 Entry，按创建时间倒序

#### Scenario: 仅后代
- **WHEN** 用户以「仅后代」范围读取某节点的 Entry
- **THEN** 返回该节点全部严格后代节点的直接 Entry，不包含该节点自身的直接 Entry

#### Scenario: 越权项目不可见
- **WHEN** 用户请求读取不属于当前 Workspace 项目的 Entry
- **THEN** 请求失败（404），不暴露数据

