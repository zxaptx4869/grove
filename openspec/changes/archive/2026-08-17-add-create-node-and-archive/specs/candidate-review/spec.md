## MODIFIED Requirements

### Requirement: 采纳时使用目录推荐

当候选存在目录推荐时，确认台 MUST 预填推荐节点；「推荐明确」时用户 SHALL 能一次采纳；「需要确认」时 MUST 展示主建议与备选；「暂无合适位置」时 MUST 让用户手动选择项目内节点，或展示新节点建议并允许用户确认“新增节点并归档”。

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
- **THEN** 确认台展示可编辑的新节点建议，用户在明确确认后一次完成节点创建与候选归档

## ADDED Requirements

### Requirement: 同一来源的新节点建议聚合

系统 MUST 将同一 Source 内路径相同的新节点建议聚合为一条展示，并显示涉及候选数量；聚合展示 MUST NOT 直接创建节点。

#### Scenario: 同路径建议合并

- **WHEN** 同一 Source 内多条待采纳候选建议相同的新节点路径
- **THEN** 确认台只显示一条节点建议，并标明涉及候选数量

#### Scenario: 聚合展示不自动创建

- **WHEN** 用户看到聚合后的新节点建议
- **THEN** 系统不自动创建节点，仍需用户对具体候选明确确认
