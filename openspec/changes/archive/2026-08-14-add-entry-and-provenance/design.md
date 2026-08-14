## Context

确认台已有 Candidate 决策，但采纳只改状态。本 change 让采纳落成正式 Entry，并保留 Source 证据。目录推荐尚未实现，因此归档时由用户手动选择项目内节点。

## Goals / Non-Goals

**Goals:**

- 新增 Entry 与 EntrySourceEvidence 模型。
- 确认台采纳时选择目录并原子创建 Entry。
- 支持 Entry 编辑与同项目移动。
- 已归档候选锁定。

**Non-Goals:**

- 标签、完整版本历史、目录推荐、新增节点并归档。

## Decisions

### D1：Entry 数据模型

新增 `entries` 表：

- `id`、`project_id`（FK projects CASCADE）、`node_id`（FK nodes CASCADE）、`candidate_id`（FK candidates SET NULL）；
- `title`、`content`、`main_type`、`info_nature`、`applicable_condition`、`note`；
- `created_at`、`updated_at`。

### D2：证据模型

新增 `entry_source_evidences` 表：

- `id`、`entry_id`（FK CASCADE）、`source_id`、`attachment_id`、`quote`；
- 归档时把 Candidate 的每条 evidence 转成一条记录。

### D3：采纳并归档 API

- `POST /api/candidates/{id}/archive`，body 含 `node_id`；服务校验 node 属于候选 Source 的 project；原子写 Entry + Evidence，并更新 Candidate 为 confirmed、写入 entry_id。
- 归档后 Candidate 锁定，决策 API 拒绝把已归档候选改为 pending。

### D4：目录必选

确认台候选编辑区从项目树拉取目录选项；未选目录禁用采纳；项目无节点时提示先去知识空间创建。

### D5：Entry 编辑 API

- `PATCH /api/entries/{entry_id}`：编辑字段与 `node_id`；校验项目归属；更新 `updated_at`。
- `GET /api/entries/{entry_id}`：返回 Entry 及证据。

### D6：知识空间展示最小化

知识空间选中节点时，展示该节点下 Entry 的基本信息与来源证据入口；本轮不做卡片/列表切换。

### D7：修改记录

不建版本表，只用 `updated_at` 表达基础修改时间。

## Risks / Trade-offs

- [目录推荐未接入，手动选目录可能增加操作] → 后续目录推荐 change 优化。
- [归档后锁定不可回退] → 用户通过编辑/删除 Entry 修正，不回到候选。
- [证据与 Entry 生命周期] → 删除 Source 前需检查唯一证据（后续 Review change 完善）。

## Migration Plan

新增 Alembic 迁移创建 `entries` 与 `entry_source_evidences`；历史 confirmed Candidate 不迁移，视为无效数据。

## Open Questions

- 删除含唯一证据 Source 的保护本轮不做，记录风险。
