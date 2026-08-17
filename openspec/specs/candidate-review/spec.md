# candidate-review Specification

## Purpose
TBD - created by archiving change add-source-review-workbench. Update Purpose after archive.
## Requirements
### Requirement: Candidate 决策状态
系统 MUST 支持 Candidate 状态为待采纳、已采纳、已拒绝；用户 MUST 能对候选执行采纳或拒绝；采纳 MUST 选择项目内目录节点并创建 Entry；已归档候选 MUST 锁定；已拒绝候选 SHALL 可重新打开为待采纳。

#### Scenario: 采纳候选
- **WHEN** 用户选择目录并采纳一条待采纳候选
- **THEN** 创建 Entry，候选状态变为已采纳并关联该 Entry

#### Scenario: 拒绝候选
- **WHEN** 用户对一条待采纳候选执行拒绝
- **THEN** 该候选状态变为已拒绝

#### Scenario: 重新打开已决定候选
- **WHEN** 用户把已拒绝候选重新打开
- **THEN** 该候选状态回到待采纳，可再次决定

### Requirement: 候选编辑后采纳
用户 SHALL 能在采纳前编辑候选的标题、核心内容、主类型、信息性质、适用条件与补充说明；编辑后的内容 MUST 作为候选与 Entry 的最终内容。

#### Scenario: 编辑后采纳
- **WHEN** 用户修改候选字段并选择目录后采纳
- **THEN** 修改后的字段被持久化，并用于创建 Entry

### Requirement: 跳过不改状态
系统 MUST 支持用户跳过当前候选继续审阅；跳过 MUST NOT 改变候选状态，被跳过的候选 MUST 保持待采纳。

#### Scenario: 跳过候选
- **WHEN** 用户跳过当前候选
- **THEN** 候选状态仍为待采纳，并在后续审阅中再次出现

### Requirement: 按 Source 审阅
系统 MUST 提供按 Source 审阅的工作台；工作台 MUST 展示当前项目内待审 Source、其原始材料与候选；工作台 MUST NOT 展示未归属项目或其他项目的 Source。

#### Scenario: 项目内待审 Source
- **WHEN** 用户进入某项目的确认台
- **THEN** 只显示该项目内且仍有待采纳候选的 Source

#### Scenario: 原始材料与候选同屏
- **WHEN** 用户选择一条待审 Source
- **THEN** 展示该 Source 的原始材料与全部候选

### Requirement: 采纳时使用目录推荐

当候选存在目录推荐时，确认台 MUST 预填推荐节点；「推荐明确」时用户 SHALL 能一次采纳；「需要确认」时 MUST 展示主建议与备选；「暂无合适位置」时 MUST 让用户手动选择项目内节点，或展示新节点建议并提供一键“新增节点并归档”；无建议时允许输入节点名称后创建归档。

#### Scenario: 推荐明确一次采纳

- **WHEN** 候选的 `routing_status` 为推荐明确
- **THEN** 目录下拉预填推荐节点，用户可直接采纳

#### Scenario: 需要确认展示主备选

- **WHEN** 候选的 `routing_status` 为需要确认
- **THEN** 确认台展示主建议、备选与理由，用户在确认后采纳

#### Scenario: 暂无合适位置手动选择

- **WHEN** 候选的 `routing_status` 为暂无合适位置且存在已有节点
- **THEN** 不预填节点，用户仍可手动选择项目内节点后采纳

#### Scenario: 暂无合适位置新增节点并归档

- **WHEN** 候选的 `routing_status` 为暂无合适位置且用户选择新增节点
- **THEN** 确认台提供一键“新增节点并归档”动作；无建议时提供节点名称输入，用户在明确确认后一次完成节点创建与候选归档

### Requirement: 同一来源的新节点建议聚合

系统 MUST 将同一 Source 内路径相同的新节点建议聚合为一条展示，并显示涉及候选数量；聚合展示 MUST NOT 直接创建节点。

#### Scenario: 同路径建议合并

- **WHEN** 同一 Source 内多条待采纳候选建议相同的新节点路径
- **THEN** 确认台只显示一条节点建议，并标明涉及候选数量

#### Scenario: 聚合展示不自动创建

- **WHEN** 用户看到聚合后的新节点建议
- **THEN** 系统不自动创建节点，仍需用户对具体候选明确确认

### Requirement: 确认台模式切换

确认台 MUST 提供「按采集审阅」与「批量处理」两种模式切换；两种模式 MUST 共享同一批待采纳候选与处理状态，批量处理 MUST NOT 存在“确认整个 Source 并自动采用所有候选”的语义。

#### Scenario: 切换到批量处理

- **WHEN** 用户在确认台点击「批量处理」
- **THEN** 页面切换到批量视图，展示项目内待采纳候选的分组与精审分流

#### Scenario: 回到按采集审阅

- **WHEN** 用户在批量视图点击「按采集审阅」
- **THEN** 页面回到逐条 Source 审阅，候选池与处理状态保持一致
