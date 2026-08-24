# behavior-signals Specification

## Purpose
TBD - created by archiving change add-behavior-signal-logging. Update Purpose after archive.
## Requirements
### Requirement: 行为信号记录模型与隔离

系统 MUST 将用户对 AI 推荐的决定记录到 `behavior_signals`；每条信号 MUST 包含 `workspace_id`、`user_id`、`signal_type`、推荐值快照（JSON）、最终值快照（JSON）、是否按推荐接受（可空）与 `created_at`；信号数据 MUST 按 Workspace 隔离，任何跨 Workspace 读取都是缺陷。

#### Scenario: 记录完整信号

- **WHEN** 用户对一条 AI 推荐做出决定
- **THEN** 系统写入一条信号，包含信号类型、推荐值快照、最终值快照、接受度与用户/Workspace 上下文

#### Scenario: 跨 Workspace 不可见

- **WHEN** 用户查询行为信号
- **THEN** 只返回当前 Workspace 的信号，不返回其他 Workspace 的数据

### Requirement: 四类信号写入

系统 MUST 在以下时机写入对应信号：修改来源项目归属时写入 `project_decision`；采纳候选（含新增节点归档）与批量改目录/拒绝时写入 `node_decision`；编辑候选字段时写入 `content_edit`（仅记录实际修改字段的 old/new）；补充来源或应用修订草稿时写入 `relation_decision`。

#### Scenario: 来源项目推荐决定

- **WHEN** 用户修改来源的项目归属
- **THEN** 系统记录推荐项目与最终项目，接受或修改、是否保持未归属

#### Scenario: 采纳候选记录目录决定

- **WHEN** 用户采纳一条候选（直接归档、新增节点归档或批量确认）
- **THEN** 系统记录推荐节点与最终节点（含是否新建节点），逐条写入

#### Scenario: 批量拒绝与改目录记录

- **WHEN** 用户批量拒绝候选或批量修改候选目录
- **THEN** 系统逐条记录 `node_decision`，拒绝时最终节点为空

#### Scenario: 编辑候选记录内容差异

- **WHEN** 用户在确认前编辑候选的标题、内容或主类型
- **THEN** 系统记录被修改字段的 AI 原值与用户新值

#### Scenario: 关系建议执行记录

- **WHEN** 用户把候选补充为已有 Entry 的来源证据，或应用修订草稿到已有 Entry
- **THEN** 系统记录关系建议（duplicate / supplement）与实际执行动作

### Requirement: 接受度判定

系统 MUST 为 `project_decision` / `node_decision` / `relation_decision` 计算是否按推荐接受：最终值等于推荐值时 MUST 为 true，不同时 MUST 为 false，推荐值为空或无推荐时 MUST 为空；`content_edit` 无接受度概念，该字段 MUST 为空。

#### Scenario: 接受推荐

- **WHEN** 用户最终决定与推荐值一致
- **THEN** 信号 `accepted` 为 true

#### Scenario: 修改或拒绝推荐

- **WHEN** 用户最终决定与推荐值不同（含拒绝且无最终值）
- **THEN** 信号 `accepted` 为 false

#### Scenario: 无推荐可对比

- **WHEN** 推荐值为空或信号类型为内容编辑
- **THEN** 信号 `accepted` 为空

### Requirement: 只读查询接口

系统 MUST 提供 `GET /api/behavior-signals` 只读接口，返回当前 Workspace 的信号列表，MUST 支持按 `signal_type` 与 `project_id` 过滤及分页；接口 MUST NOT 提供修改或删除能力。

#### Scenario: 按类型与项目过滤

- **WHEN** 用户携带 `signal_type` 与 `project_id` 查询
- **THEN** 返回当前 Workspace 内匹配的信号列表

#### Scenario: 只读不可写

- **WHEN** 用户尝试通过该接口修改或删除信号
- **THEN** 请求失败，数据不变

### Requirement: 信号数据保留

删除 Source、Project、Candidate 后，关联信号 MUST 保留（外键置空），MUST NOT 级联删除，以支持长期趋势分析。

#### Scenario: 删除来源后信号保留

- **WHEN** 用户删除一个已产生信号的来源
- **THEN** 来源与候选删除，但信号记录仍可查询，来源/候选引用为空

