## Context

上一 change 按 `status=done` 锁定来源改/删，但 done 只表示提取完成，与候选确认无关，导致过度锁定。产品确认：锁定条件应为「已产生正式知识」，并在来源列表展示候选确认副状态，让锁定原因可见；处理中应临时锁定；「已完成」文案改为「提取完成」。

## Goals / Non-Goals

**Goals:**

- 改/删仅在已产生正式知识或处理中时禁止；
- 来源列表展示审阅副状态与 pending_candidate_count；
- 删除有待确认候选的来源二次确认；
- 状态文案改为「提取完成」。

**Non-Goals:**

- 不为已产生正式知识的来源提供删除/移动途径。

## Decisions

### D1：锁定条件修正

- `update_source`：保留 `project_locked`（已确认候选或 Entry 证据）409；新增 `status == PROCESSING` 409；**移除 `status == DONE` 409**。
- `delete_source`：任一 Entry 证据即 409（不再区分唯一/非唯一，因为证据来源必为 done 且锁定）；新增 `status == PROCESSING` 409；**移除 `status == DONE` 409**。

### D2：审阅副状态

`SourceOut` 增加 `pending_candidate_count`（批量一次 IN 分组计算）。前端在 `status=done` 时按（pending、evidence）派生副徽标：待确认 N 条 / 部分确认 / N 条正式知识 / 已处理。

### D3：前端可见性

`SourceList`：

- 操作（改归属/删除）仅在 `!project_locked && status != 'processing'` 时展示；
- 删除在 `pending_candidate_count > 0` 时弹二次确认，提示连带删除候选；
- 状态文案 `done → 提取完成`。

## Risks / Trade-offs

- [删除提取完成但候选未确认的来源会丢失候选] → 二次确认明确提示，用户知情后决定。
- [pending_candidate_count 查询成本] → 列表一次 IN 分组，可接受。

## Migration Plan

无数据库变更。

## Open Questions

- 无。
