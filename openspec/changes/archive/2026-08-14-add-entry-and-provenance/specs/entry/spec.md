## ADDED Requirements

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
