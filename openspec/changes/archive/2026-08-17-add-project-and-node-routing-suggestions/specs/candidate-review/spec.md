## ADDED Requirements

### Requirement: 采纳时使用目录推荐
当候选存在目录推荐时，确认台 MUST 预填推荐节点；「推荐明确」时用户 SHALL 能一次采纳；「需要确认」时 MUST 展示主建议与备选；「暂无合适位置」时 MUST 让用户手动选择项目内节点。

#### Scenario: 推荐明确一次采纳
- **WHEN** 候选的 `routing_status` 为推荐明确
- **THEN** 目录下拉预填推荐节点，用户可直接采纳

#### Scenario: 需要确认展示主备选
- **WHEN** 候选的 `routing_status` 为需要确认
- **THEN** 确认台展示主建议、备选与理由，用户在确认后采纳

#### Scenario: 暂无合适位置手动选择
- **WHEN** 候选的 `routing_status` 为暂无合适位置
- **THEN** 不预填节点，用户手动选择项目内节点后采纳
