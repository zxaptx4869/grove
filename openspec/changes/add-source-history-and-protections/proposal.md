## Why

来源管理目前散落在项目侧栏「采集与来源」里，项目菜单偏多；来源会随使用不断积累，收集箱右侧全量列表没有搜索/分页，久了不便；且已归档来源仍可随意改归属或删除，可能把已确认 Entry 的证据移出项目或造成无来源正式知识，破坏可追溯。需要把来源管理收敛到全局收集箱体系，并提供全量历史查询与状态保护。

## What Changes

- **收集箱**：右侧列表改为「最近来源」最近 10 条（保留全部/未归属筛选）；右上角与筛选 tab 同高新增「查看全部来源」按钮。
- **来源历史页**：新增全屏路由 `/sources`（不进侧栏菜单）：项目/状态/未归属筛选、关键词搜索、分页（每页 20 条）、行内管理操作。
- **项目侧栏**：移除「采集与来源」入口；项目首页提供「来源与处理状态」入口，跳转 `/sources?project=<id>` 并预筛该项目；旧 `/projects/:id?view=sources` 路由保留兼容。
- **后端**：`/api/sources` 支持 `limit`（最近来源）；新增 `/api/sources/query` 分页查询（project_id / unassigned / status / q / limit / offset，返回 items + total）；`SourceOut` 增加 `project_locked` 与 `evidence_entry_count`。
- **状态保护**：已有确认候选或 Entry 证据的来源禁止改归属（409）；删除时若该来源是某 Entry 的唯一证据则阻止（409），还有其他证据则前端二次确认并提示影响条数。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `source-management`: 最近来源展示、全量历史查询（筛选/搜索/分页）、改归属约束、删除保护与 SourceOut 状态字段。
- `product-shell`: 侧栏导航收敛——全局一级菜单固定顶部、项目上下文置于其下、项目导航移除「采集与来源」；新增 `/sources` 全屏历史页路由（不进侧栏菜单）。

## Impact

- 后端：`api/sources.py`（列表 limit、新增 query 端点、改归属/删除保护）、`schemas/source.py`（`SourceOut` 新字段、`SourcePageOut`）。
- 前端：`InboxPage`（最近 10 + 查看全部来源按钮）、新增 `SourceHistoryPage`、`AppShell`（移除入口）、`App.tsx`（`/sources` 路由）、`ProjectPage` 项目首页来源入口、`SourceList`（禁用改归属 + 删除确认）。
- 测试：后端保护与分页查询用例；前端最近来源/历史页/按钮用例。
- 数据与依赖：无迁移、无新增依赖。

## Non-Goals

- 不做来源批量操作（批量删除/改归属）。
- 不做来源详情大图页（沿用现有弹窗/列表能力）。
- 不新增全局一级菜单（`/sources` 不进侧栏）。
- 不做虚拟滚动（分页即可）。
- 不改 AI 阅读、确认台候选流程。
