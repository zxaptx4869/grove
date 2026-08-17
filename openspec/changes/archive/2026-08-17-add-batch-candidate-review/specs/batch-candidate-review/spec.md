## ADDED Requirements

### Requirement: 项目批量候选列表

系统 MUST 提供项目级批量候选列表接口，返回该项目内全部待采纳候选，并按候选来源附加 `source_title`、`source_note` 与 `review_band`；接口 MUST 只返回当前 Workspace 项目内的候选。

#### Scenario: 返回项目内待采纳候选

- **WHEN** 已登录用户请求某项目的批量候选列表
- **THEN** 返回该项目内全部待采纳候选，每条包含来源标题、来源说明、路由状态、风险标记与 `review_band`

#### Scenario: 越权项目不可见

- **WHEN** 用户请求不属于当前 Workspace 项目的批量候选列表
- **THEN** 请求失败（404），不返回任何候选

### Requirement: 快审与精审分流

系统 MUST 将候选标记为 `quick` 或 `detailed`：`candidate_kind` 为推荐、`routing_status` 为推荐明确、`recommended_node_id` 非空且无 `risk_flags` 的候选为 `quick`，其余为 `detailed`。

#### Scenario: 推荐明确无风险进快审

- **WHEN** 候选为推荐候选、推荐明确、有真实推荐节点且无风险标记
- **THEN** 该候选 `review_band` 为 `quick`

#### Scenario: 高风险或非明确进入精审

- **WHEN** 候选存在 `risk_flags`，或路由状态为需要确认/暂无合适位置，或属于其他发现
- **THEN** 该候选 `review_band` 为 `detailed`

### Requirement: 按推荐目录分组展示

批量视图 MUST 将快审候选按推荐目录分组，分组标题展示目录路径与候选数量；候选行 MUST 展示标题、来源标题、主类型，并可展开来源说明与证据。

#### Scenario: 同目录候选成组

- **WHEN** 多条快审候选推荐到同一目录节点
- **THEN** 批量视图将它们归入同一分组，标题显示该目录路径与数量

#### Scenario: 展开来源证据

- **WHEN** 用户在批量视图展开某条候选
- **THEN** 展示其来源标题、来源说明与证据引用片段

### Requirement: 批量确认并归档

系统 MUST 支持对选中的快审候选执行批量确认：默认按候选自身推荐节点创建 Entry，或使用统一目录节点覆盖；每条候选 MUST 独立成功或失败，成功项持久化，失败项返回原因并保持待采纳。

#### Scenario: 全部成功

- **WHEN** 用户对多条有推荐节点的候选执行批量确认
- **THEN** 每条候选创建 Entry 并变为已采纳，返回各自成功状态

#### Scenario: 部分失败可重试

- **WHEN** 批量确认中某条候选缺少目录或已处理
- **THEN** 该候选返回失败原因并保持待采纳，其余候选正常归档，成功项不因失败项回滚

### Requirement: 批量拒绝

系统 MUST 支持对选中的候选执行批量拒绝，将候选状态改为已拒绝。

#### Scenario: 批量拒绝成功

- **WHEN** 用户对多条待采纳候选执行批量拒绝
- **THEN** 候选全部变为已拒绝，并从待采纳列表中移除

### Requirement: 修改目录

系统 MUST 支持在批量视图为选中候选选择一个当前项目内的统一目录节点，并在后续批量确认中使用该节点覆盖候选自身推荐。

#### Scenario: 统一目录覆盖

- **WHEN** 用户为选中的候选设置统一目录节点并批量确认
- **THEN** 这些候选归档到统一节点，而非各自推荐节点

### Requirement: 精审候选返回逐条模式

批量视图 MUST 对 `detailed` 候选禁用批量勾选，并允许用户一键回到按 Source 的逐条审阅。

#### Scenario: 精审候选不参与快审

- **WHEN** 用户查看批量视图
- **THEN** `detailed` 候选的批量勾选被禁用，并明确标记为需精审

#### Scenario: 一键转精审

- **WHEN** 用户点击某条精审候选的「精审」动作
- **THEN** 页面切换到按采集审阅并定位到该候选所在 Source
