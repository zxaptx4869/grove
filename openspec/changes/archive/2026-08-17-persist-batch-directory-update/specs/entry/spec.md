## ADDED Requirements

### Requirement: 归档优先使用用户确认目录

系统 MUST 在批量归档候选时，优先使用候选的用户确认目录节点（`user_node_id`）；未设置时使用候选推荐节点。

#### Scenario: 使用用户确认目录归档

- **WHEN** 候选存在用户确认目录节点
- **THEN** 批量采纳创建 Entry 时使用该节点

#### Scenario: 回退推荐节点

- **WHEN** 候选不存在用户确认目录节点
- **THEN** 批量采纳使用候选推荐节点
