## Why

确认台已经能采纳候选，但目录选择完全靠人工在目录树里挑，每条候选都要重复选择；全局收集箱的来源也没有 AI 项目归属建议。这是 P0-B「整理效率闭环」的第一步：让 Organizing Agent 为来源推荐所属项目、为候选推荐真实目录节点，并用三档可解释状态把「确认正确，直接采纳」变成默认路径。

## What Changes

- 项目推荐：全局收集箱来源在处理时由 AI 推荐所属项目，不明确时保持未归属；项目内来源直接使用当前项目，不调用 AI 猜测。
- 目录推荐：每条候选推荐真实 `node_id`、备选、理由和三档路由状态。
- 路由步骤：独立、可重跑；项目内来源处理完立即路由，全局来源在用户确认项目后路由，修改来源项目后重新路由。
- 一次确认：确认台目录下拉预填推荐节点；「推荐明确」一键采纳，「需要确认」展示主建议与备选，「暂无合适位置」让用户手动选现有节点。
- Agent 上下文：Organizing Agent 的路由模式补充项目真实目录节点（`id`、名称、说明、路径）。

## Capabilities

### New Capabilities

- `routing-suggestions`: 来源项目推荐、候选目录推荐、三档路由状态与可重跑的路由步骤。

### Modified Capabilities

- `candidate-review`: 采纳流程使用目录推荐预填，并按三档路由状态提供一次确认、需确认或手动选择。
- `source-management`: 修正 Source 审阅状态规格，改为按候选决策结果实时派生、不落库。

## Impact

- 后端：`Source` 增加 `recommended_project_id` 与 `project_recommendation_reason`；`Candidate` 增加 `recommended_node_id`、`node_alternatives`、`node_reason`、`routing_status`（含迁移）；新增路由服务与触发；Organizing Agent 路由上下文扩展。
- 前端：收集箱展示项目推荐并可确认；确认台目录选择预填推荐并区分三档表现；修改来源项目后触发重新路由。
- 无新外部依赖。

## Non-Goals

- 无合适位置时「新增节点并归档」（`add-create-node-and-archive`）。
- 与已有 Entry 的关系建议、去重或补充来源（`add-entry-relation-suggestions`）。
- 跨 Source 批量处理（`add-batch-candidate-review`）。
- 项目推荐与目录推荐的可解释百分比（只使用三档路由状态）。
- 目录 Agent 共创或调整目录。
