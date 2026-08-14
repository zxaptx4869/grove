## MODIFIED Requirements

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
