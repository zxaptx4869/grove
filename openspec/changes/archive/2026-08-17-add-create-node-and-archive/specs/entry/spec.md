## MODIFIED Requirements

### Requirement: 采纳并归档

系统 MUST 在用户选择目录后原子创建 Entry，并把 Candidate 关联到 Entry；当用户确认新增节点时，系统 MUST 在同一事务内先创建或复用节点，再创建 Entry 与证据；归档成功后 Candidate MUST 不再允许重新打开。

#### Scenario: 原子归档

- **WHEN** 用户选择目录并采纳候选
- **THEN** Entry 与证据关系创建成功，Candidate 关联 Entry 并变为已采纳

#### Scenario: 归档后锁定候选

- **WHEN** 候选已归档为 Entry
- **THEN** 该候选不能重新打开为待采纳

#### Scenario: 新增节点并归档原子成功

- **WHEN** 用户在无合适目录时确认“新增节点并归档”
- **THEN** 节点与 Entry 及证据关系在同一事务内创建，Candidate 关联 Entry 并变为已采纳

#### Scenario: 新增节点并归档失败不留半成品

- **WHEN** “新增节点并归档”在创建节点或写入 Entry/证据的任一环节失败
- **THEN** 不留下新节点、Entry 或已变化的 Candidate，候选仍保持待采纳

#### Scenario: 复用同名同父节点

- **WHEN** 用户确认的新节点在目标父节点下已存在同名节点
- **THEN** 系统复用该已有节点归档 Entry，不创建重复节点
