## Context

确认台已能按候选编辑并选择目录后采纳，但目录选择纯手动；收集箱也没有项目推荐。Organizing Agent 目前一次处理只做「语义拆分 + 候选」，上下文只有采集说明、项目说明和原始材料，不包含真实目录节点。本 change 增加项目推荐与目录推荐，把「确认正确、直接采纳」变成默认路径。

## Goals / Non-Goals

**Goals:**

- 全局收集箱来源处理时推荐所属项目；项目内来源不猜项目。
- 每条候选推荐真实 `node_id` 主建议、备选、理由和三档路由状态。
- 目录推荐可重跑：项目内来源处理完即路由，全局来源确认项目后路由，修改项目重新路由。
- 确认台目录选择预填推荐，按三档状态提供一次确认/需确认/手动选择。

**Non-Goals:**

- 新增节点并归档、与已有 Entry 关系判断、批量处理、可解释百分比、目录共创。

## Decisions

### D1：项目推荐落在 Source

`Source` 增加 `recommended_project_id`（可空，无外键，仅建议）与 `project_recommendation_reason`（可空文本）。只在全局收集箱来源处理时生成；项目内来源不生成、直接使用当前项目。用户确认后写 `project_id`，推荐字段自然失效但保留审计。

理由：项目推荐是来源级的临时建议，挂在 Source 上最直接；无外键避免项目删除时的级联噪音。

### D2：目录推荐落在 Candidate

`Candidate` 增加：

- `recommended_node_id`（可空，无外键，路由时校验真实节点）；
- `node_alternatives`（JSON 文本，`[{node_id, reason}]`）；
- `node_reason`（主建议理由，可空）；
- `routing_status`（`recommended` / `needs_review` / `no_suitable`，未路由时为 `pending`）。

理由：每条候选独立推荐，因此放在 Candidate；无外键避免节点删除时影响候选，应用层在路由时校验。

### D3：路由是独立可重跑步骤

新增路由服务，仍属于 Organizing Agent 职责，但用「路由模式」单独调用：

```text
候选列表 + 项目真实节点树(id/name/description/path)
        ↓ Organizing Agent（路由模式）
每条候选 → 主 node_id + 备选 + 理由 + 三档状态
        ↓ 应用层校验 node_id 真实存在后落库
```

理由：目录推荐依赖项目目录，且「修改项目后重新计算」要求路由独立于提取；与处理任务「推荐归档」步骤一致。

### D4：路由触发时机

- 项目内来源：`OrganizingProcessingProvider` 在保存成功 Extraction 后同步调用路由（仍在同一个处理任务内）。
- 全局来源：用户确认/修改项目时同步触发路由；路由前先把候选标记为 `pending`，完成后返回推荐。
- 修改项目后：清除该来源候选旧推荐并重新路由，不复制候选或 Entry。

取舍：全局来源的同步路由会在 PATCH 响应中阻塞一次 AI 调用。当前离线/演示模型即时返回，且确认台即使路由未完成仍允许手动选节点；异步队列优化留待后续 change。

### D5：Agent 输入与输出扩展

- 提取阶段：`ExtractionDraft` 增加 `recommended_project_id` 与 `project_recommendation_reason`；全局来源的上下文补充「Workspace 项目列表（id/name/description）」。
- 路由阶段：新增 `RoutingDraft`（每候选的主建议、备选、理由、三档状态）；上下文补充「项目节点列表」。
- 离线 demo：确定性输出——项目推荐为空、目录推荐取项目第一个节点（无节点则 `no_suitable`）。

### D6：三档路由状态语义

- `recommended`：主建议明确，可一次采纳；
- `needs_review`：有建议但不确定，展示主建议与备选；
- `no_suitable`：无合适节点，用户手动选现有节点；
- `pending`：尚未路由完成，界面不冒充有推荐。

### D7：一次确认交互

确认台目录下拉预填 `recommended_node_id`；`recommended` 直接高亮「采纳」；`needs_review` 展示主建议/备选/理由；`no_suitable` 不预填。项目归属仍在收集箱确认（来源级），确认台只处理候选内容/类型/目录。

### D8：数据迁移与兼容

一个 Alembic 迁移同时为 `sources` 与 `candidates` 增加上述列；新增列均 `nullable`，老数据回填为 `NULL`/`pending`。无破坏性变更。

## Risks / Trade-offs

- [路由是额外 AI 调用，增加处理耗时] → 项目内来源在既有处理任务内串行；全局来源同步阻塞 PATCH，离线即时、真实 Provider 可能有数秒延迟，后续可异步化。
- [Agent 输出非法 node_id] → 应用层校验，非法推荐丢弃或降级为 `no_suitable`。
- [异步路由中途失败] → 候选保持 `pending`，后续触发重路由可恢复；不阻塞确认台（用户仍可手动选节点）。
- [推荐字段无外键，节点删除后可能悬空] → 路由时按当前真实节点校验，悬空推荐在下一次路由被覆盖。

## Migration Plan

新增迁移为 `sources`/`candidates` 增加可空列；无回填。回滚即删列。

## Open Questions

- 全局来源的异步路由，具体复用「ProcessingTask 增加 route 步骤」还是独立轻量队列，实施时按现有 Worker 结构确定。
- `node_alternatives` 的备选数量上限是否需要在 prompt 中限制（建议 2 条以内），实施时确定。
