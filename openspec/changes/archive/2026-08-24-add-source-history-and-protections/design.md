## Context

来源管理目前占项目侧栏一个菜单且缺少全量查询能力；来源积累后收集箱右栏全量列表不便；已归档来源可随意改归属/删除，破坏可追溯。产品讨论确认：采集是高频主动作，保持收集箱左侧常驻；查全量来源是低频补足动作，放独立全屏页；项目侧栏菜单收敛。

## Goals / Non-Goals

**Goals:**

- 收集箱右侧改为最近 10 条来源，右上角提供「查看全部来源」入口；
- 新增全屏来源历史页（筛选/搜索/分页/操作），不进侧栏菜单；
- 项目侧栏移除「采集与来源」，项目首页提供预筛来源入口；
- 已归档来源禁止改归属；唯一证据来源删除受保护；删除二次确认。

**Non-Goals:**

- 不做批量操作、详情大图页、虚拟滚动；不新增一级菜单。

## Decisions

### D1：后端查询扩展

- `GET /api/sources` 增加可选 `limit`（1-100），保持返回 `list[SourceOut]`，供收集箱「最近来源」；
- 新增 `GET /api/sources/query`：参数 `project_id / unassigned / status / q / limit / offset`，返回 `SourcePageOut { items, total, limit, offset }`，供历史页分页；
- `_source_out` 批量组装新增字段：`project_locked`（存在 confirmed 候选且 entry_id 非空，或 EntrySourceEvidence 引用）与 `evidence_entry_count`（去重 Entry 数），列表场景用一次 IN 查询分组避免 N+1。

### D2：状态保护

- 改归属：`update_source` 中若 `project_locked` 成立则 409，detail 说明"该来源已被正式知识引用，如需移动请先处理关联 Entry"；pending 候选不受影响（仍清路由重跑）；
- 删除：`delete_source` 统计引用该 Source 的 EntrySourceEvidence；若存在某 Entry 仅此一条证据则 409 阻止；否则允许删除，前端在 `evidence_entry_count>0` 时二次确认并提示影响条数。

### D3：前端

- `InboxPage`：右侧请求 `limit=10`，标题注明"最近来源"；右上角与 tabs 同高放「查看全部来源」按钮（跳 `/sources`）；
- 新增 `SourceHistoryPage`（`/sources`）：筛选（项目/状态/未归属）+ 关键词搜索 + 分页（20/页）+ 复用 `SourceList` 行内操作；
- `SourceList`：`project_locked` 时禁用改归属下拉并提示；删除按钮 `evidence_entry_count>0` 时先确认；
- `AppShell`：项目导航移除「采集与来源」；`App.tsx` 注册 `/sources`；
- `ProjectPage` 项目首页加「来源与处理状态」入口，跳 `/sources?project=<id>` 预筛。

### D4：兼容

`/projects/:id?view=sources` 路由保留（`ProjectSources` 组件不删）；`/api/sources` 无 limit 时行为不变。

## Risks / Trade-offs

- [project_locked 判断口径] → 以"confirmed 候选（含 entry_id）或存在 EntrySourceEvidence"为准，宁可锁紧不可放行。
- [批量字段查询性能] → 列表场景一次性 IN 分组查询，来源量大时仍可控；后续必要时再优化。
- [历史页与收集箱两处操作入口] → 同一 SourceList 组件与同一后端保护，行为一致。

## Migration Plan

无数据库变更；新字段仅响应层计算。回滚即撤销端点与 UI 入口。

## Open Questions

- 来源历史页是否默认展示未归属（与收集箱一致），实施时按收集箱默认筛选对齐。
