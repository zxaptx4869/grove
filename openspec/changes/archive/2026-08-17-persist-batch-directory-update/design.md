## Context

批量「修改目录」当前只设置前端 `overrideNodeId`，确认弹窗仅关闭，无任何持久化，导致用户看不到生效。本 change 把统一目录写入每条选中候选。

## Goals / Non-Goals

**Goals:**

- 确认即持久化到候选，列表刷新、勾选清空、按钮回灰。
- 批量采纳使用持久化目录，未设置时回退推荐节点。

**Non-Goals:**

- 不改快审/精审分流。
- 不做逐条改目录。

## Decisions

### D1：`Candidate.user_node_id`

新增可空 `user_node_id`（无外键，写入时校验属于项目），语义为“用户确认的统一目录”，与 AI 推荐字段分离。

### D2：批量更新目录接口

```text
POST /api/projects/{project_id}/review/candidates/batch-update-directory
body: { candidate_ids, node_id }
```

校验候选都属于当前项目且待采纳、节点属于当前项目，逐条写入 `user_node_id`，单次提交。

### D3：批量确认节点优先级

`confirm` 时按 `payload.node_id` → `candidate.user_node_id` → `candidate.recommended_node_id` 选择归档节点。

### D4：前端交互

- 「修改目录」弹窗确认按钮调用持久化接口，成功后失效 `review-candidates`、`review-sources`，清空勾选与弹窗。
- 批量列表按 `user_node_id ?? recommended_node_id` 分组，刷新后候选会移动到新目录组。

## Risks / Trade-offs

- [用户设置后再次修改] → 新值覆盖旧值，重复调用幂等。
- [节点被删除] → 归档时沿用节点归属校验，失败项按 partial 语义留在列表。

## Migration Plan

一个 Alembic 迁移新增可空列；回滚即删列。

## Open Questions

无。
