# candidate-review Specification

## Purpose
TBD - created by archiving change add-source-review-workbench. Update Purpose after archive.
## Requirements
### Requirement: Candidate 决策状态
系统 MUST 支持 Candidate 状态为待采纳、已采纳、已拒绝；用户 MUST 能对候选执行采纳或拒绝；用户 SHALL 能把已采纳或已拒绝的候选重新打开为待采纳，以修正误操作。

#### Scenario: 采纳候选
- **WHEN** 用户对一条待采纳候选执行采纳
- **THEN** 该候选状态变为已采纳，且仍保留其来源证据

#### Scenario: 拒绝候选
- **WHEN** 用户对一条待采纳候选执行拒绝
- **THEN** 该候选状态变为已拒绝

#### Scenario: 重新打开已决定候选
- **WHEN** 用户把已采纳或已拒绝的候选重新打开
- **THEN** 该候选状态回到待采纳，可再次决定

### Requirement: 候选编辑后采纳
用户 SHALL 能在采纳前编辑候选的标题、核心内容、主类型、信息性质、适用条件与补充说明；编辑后的内容 MUST 作为该候选的最终内容。

#### Scenario: 编辑后采纳
- **WHEN** 用户修改候选字段后采纳
- **THEN** 修改后的字段被持久化，候选状态变为已采纳

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

