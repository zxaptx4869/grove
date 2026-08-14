## Context

当前候选只读，`Candidate.status` 固定为 `pending`，`Source.status` 只表达处理状态。确认台需要把候选决策与 Source 审阅状态拆开，保持处理管道不变。

## Goals / Non-Goals

**Goals:**

- Candidate 决策状态与编辑。
- 按 Source 审阅工作台与 Source 内批量决策。
- Source 审阅状态派生。

**Non-Goals:**

- Entry、目录推荐、跨 Source 批量、AI 项目推荐。

## Decisions

### D1：Candidate 状态

`Candidate.status` 取值：`pending / confirmed / rejected`。UI 文案为待采纳 / 已采纳 / 已拒绝。决策作用于 Candidate，Source 只做分组与进度。

### D2：跳过是前端导航

「跳过」不落库、不改状态；前端维护当前候选游标，切到下一条。刷新后跳过项仍为待采纳。

### D3：编辑后采纳

`PATCH /api/candidates/{id}` 更新 `title/content/main_type/info_nature/applicable_condition/note`；采纳或拒绝用 `POST /api/candidates/{id}/decision`。

### D4：重新打开已决定候选

允许 `status` 从 `confirmed/rejected` 回到 `pending`，方便修正误操作；此动作同步重算 Source 审阅状态。

### D5：Source.review_status 独立字段

新增 `review_status`：`pending_review / partial_review / reviewed`。处理成功置 `pending_review`；每次决策后按当前候选状态重算。`Source.status` 继续表示处理状态，不被覆盖。

### D6：按 Source 审阅 API

- `GET /api/projects/{project_id}/review/sources`：返回项目内待审 Source 与候选计数。
- `GET /api/sources/{source_id}/candidates`：已有接口，复用。
- `PATCH /api/candidates/{id}`：编辑候选。
- `POST /api/candidates/{id}/decision`：单条决策。
- `POST /api/sources/{source_id}/candidates/batch-decision`：Source 内批量决策。

决策后重算 Source.review_status。

### D7：确认台页面

项目导航「知识空间」下新增「确认台」，路由 `/projects/:projectId/review`。页面按原型三栏组织：待审 Source 列表/抽屉、原始材料与证据、候选列表与决策操作。本轮不显示目录推荐，不显示批量处理 Tab。

### D8：测试策略

后端测试决策状态机、编辑、重新打开、批量决策、Source 审阅状态派生、Workspace 隔离。前端测试确认台渲染、采纳/拒绝/跳过与批量操作。

## Risks / Trade-offs

- [决策后暂不生成 Entry] → 下一项 `add-entry-and-provenance` 消费 `confirmed` Candidate。
- [跳过不落库] → 刷新后回到待采纳，符合预期。
- [未归属 Source 不在确认台] → 用户先到收集箱归属项目。

## Migration Plan

新增 Alembic 迁移为 `sources` 增加 `review_status`（默认 `pending_review`）。

## Open Questions

- 待审 Source 列表采用常驻左栏还是抽屉（按原型用抽屉，待实现时确定）。
