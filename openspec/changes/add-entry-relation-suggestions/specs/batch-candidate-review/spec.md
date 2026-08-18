## MODIFIED Requirements

### Requirement: 快审与精审分流

系统 MUST 将候选标记为 `quick` 或 `detailed`：`candidate_kind` 为推荐、`routing_status` 为推荐明确、`recommended_node_id` 非空、无 `risk_flags`，且 `relation_status` 为 `pending` 或 `new` 的候选为 `quick`，其余为 `detailed`。

#### Scenario: 推荐明确无风险进快审

- **WHEN** 候选为推荐候选、推荐明确、有真实推荐节点、无风险标记，且关系状态为 `new` 或 `pending`
- **THEN** 该候选 `review_band` 为 `quick`

#### Scenario: 高风险或非明确进入精审

- **WHEN** 候选存在 `risk_flags`，或路由状态为需要确认/暂无合适位置，或属于其他发现
- **THEN** 该候选 `review_band` 为 `detailed`

#### Scenario: 关系建议进入精审

- **WHEN** 候选关系状态为 `duplicate`、`supplement` 或 `conflict`
- **THEN** 该候选 `review_band` 为 `detailed`
