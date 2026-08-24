## Why

P0-B 唯一未勾项：系统具备完整「AI 推荐 → 用户确认」流程，但没有行为数据，无法回答蓝图 MVP 的两个验证问题（用户是否愿意确认 AI 推荐、整理效率如何），也无法为后续个性化积累「AI 推荐 vs 用户期望」的对齐样本。现有业务表在编辑时会覆盖 AI 原值、批量路径不落推荐对比，事后无法还原，需要专门的信号记录。

## What Changes

- 新增 `behavior_signals` 表与 Alembic 迁移：记录用户对 AI 推荐的决定，每条包含 Workspace、用户、信号类型、推荐值快照、最终值快照、是否按推荐接受与时间。
- 四类信号：项目推荐决定（`project_decision`）、目录推荐决定（`node_decision`，含新增节点与拒绝）、内容与类型编辑（`content_edit`，字段级 old/new）、关系建议执行（`relation_decision`）；批量确认/拒绝/改目录逐条记录同类信号。
- 在现有后端业务 service 内顺带写入信号（编辑候选、采纳/新节点归档、补充来源、应用修订、批量决策、修改来源归属），前端零埋点。
- 新增只读查询接口 `GET /api/behavior-signals`，按 Workspace 隔离，支持信号类型与项目过滤、分页。
- 删除 Source / Project / Candidate 后信号记录保留（外键置空），用于长期分析。

## Capabilities

### New Capabilities

- `behavior-signals`: 用户对 AI 推荐决定的信号记录、接受度判定与只读查询。

### Modified Capabilities

（无）

## Impact

- 后端：新增 `BehaviorSignal` 模型与迁移、`record_behavior_signal` 服务、`sources / review / entry` 相关接口与 service 埋点、新查询接口；API 层补充当前用户依赖以记录 user_id。
- 前端：无改动。
- 测试：pytest 覆盖四类信号写入、接受度判定、Workspace 隔离、数据保留与只读接口。
- 数据：新增表，无破坏性变更。

## Non-Goals

- 不做统计面板 / 分析 UI、不做个性化推荐算法；
- 不记录浏览、搜索等非决策行为；
- 不改变现有业务行为与接口语义；
- 不为信号新增前端埋点或独立上报接口。
