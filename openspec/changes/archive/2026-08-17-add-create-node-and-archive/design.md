## Context

当前确认台按 Source 逐条处理候选。目录推荐已落到候选的三档路由状态，但 `no_suitable` 分支只能手动选择已有节点；当项目目录为空或没有匹配节点时，用户无法在一次确认中完成归档。本 change 补齐“无合适节点时新增节点并归档”，并保证节点建议去重与操作原子性。

现状关键点：

- `Candidate` 已有 `recommended_node_id`、`node_alternatives`、`node_reason`、`routing_status` 字段，用于已有节点推荐。
- `archive_candidate` 已能在一次 `commit` 内创建 Entry、证据并锁定候选，但要求传入已存在的 `node_id`。
- `create_node` 是独立接口，与归档不在同一事务。
- 前端 `ReviewPage` 在 `no_suitable` 时目录下拉为空或手动选择，采纳按钮在无节点时不可用。

## Goals / Non-Goals

**Goals:**

- 路由 Agent 在 `no_suitable` 时输出并落库一条新节点建议（名称、可选父节点、理由）。
- 确认台在 `no_suitable` 时展示可编辑的新节点建议，并允许一次“新增节点并归档”。
- 新节点建议按路径去重展示；创建时复用同名同父节点，避免重复节点。
- 节点创建与候选归档在同一事务内完成，失败不留半成品。

**Non-Goals:**

- 不实现跨 Source 批量处理。
- 不实现与已有 Entry 的关系判断。
- 不在 `recommended` / `needs_review` 状态新增完整的“更改目录后新增节点”入口。
- 不实现 Directory Agent 或目录共创。

## Decisions

### D1：新节点建议落在 Candidate

`Candidate` 增加三个可空字段：

- `new_node_name`（`String(128)`，可空）；
- `new_node_parent_id`（`BigInteger`，可空，无外键，保存时校验）；
- `new_node_reason`（`Text`，可空）。

理由：新节点建议与目录推荐一样是候选级临时建议，挂在 Candidate 上最直接；无外键避免节点删除时影响候选，应用层在写入和创建时校验。为去重展示提供原始建议数据，同时不引入独立 NodeSuggestion 实体，避免本轮过度设计。

### D2：路由 Agent 在 `no_suitable` 时输出建议

`NodeRecommendationDraft` 增加 `new_node_name`、`new_node_parent_id`、`new_node_reason`。`ROUTING_SYSTEM_PROMPT` 补充规则：只有 `routing_status` 为 `no_suitable` 时才可输出新节点建议；`new_node_parent_id` 必须是给定节点 id 或空。`_apply_recommendation` 仅对 `no_suitable` 结果保存新节点建议，并校验父节点在 `node_ids` 中或为空；非法父节点按根节点处理。离线路由在无节点时保持 `no_suitable` 且不输出建议，前端提供空白表单。

理由：建议在路由时一并生成，确认台即时展示且去重自然；沿用现有“AI 只输出建议、应用层校验后落库”的边界。

### D3：新增专用原子归档接口

新增：

```text
POST /api/candidates/{candidate_id}/archive-with-new-node
```

请求体 `NewNodeArchiveRequest`：

- `name`：必填，1–128 字符；
- `parent_id`：可空，空表示根节点；
- `description`：可空，最多 2000 字符。

响应复用 `EntryOut`。不改动现有 `/archive` 接口，保持既有语义稳定。

理由：显式表达“创建/复用节点并归档”的组合动作，避免扩展现有接口造成 `node_id` 与新节点二选一的联合校验复杂度。

### D4：原子归档服务

新增 `archive_candidate_with_new_node(db, candidate, payload)`：

1. 校验候选为 `pending`、来源已归属项目。
2. 校验 `parent_id` 为空或属于当前项目。
3. 规范化 `name`，在当前项目同父节点下按不区分大小写匹配同名节点；命中则复用，否则创建节点并 `flush`。
4. 仅当真正创建节点时调用 `schedule_refresh`。
5. 复用现有 `archive_candidate` 完成 Entry/证据/候选确认写入。

接口在 `archive_candidate_with_new_node` 返回后执行一次 `db.commit()`。任何异常在提交前抛出，依赖 `get_db_session` 的会话上下文回滚，保证不留半成品。

理由：最小改动复用已验证的归档逻辑；节点查找在应用层用 Python 归一化比较，避免依赖 SQLite/MySQL 的排序规则差异。

### D5：前端去重与交互

`CandidatePayload` 增加 `new_node_suggestion`（可空对象：`name`、`parent_id`、`reason`）。`ReviewPage` 仅对 `routing_status === 'no_suitable'` 的待采纳候选渲染新节点分支：

- 保留现有节点下拉用于“改到最接近节点”。
- 保留“跳过”按钮，表示暂存未归档。
- 新增“新增节点并归档”表单，预填建议名称与父节点，允许编辑名称、父节点、说明。
- 如果建议路径在现有目录树中已存在同名同父节点，则解析为已有节点并直接支持采纳，不重复显示“新增”。

同一 Source 内按“父节点 + 归一化名称”分组新节点建议，显示“本来源有 N 条候选建议新增「路径」”，点击跳到对应候选。

数据变更通过 `useGroveMutation`，显式 `invalidates`：`sourceCandidates`、`reviewSources`、`projectTree`。创建节点后目录树与候选列表刷新，后续相同路径建议会解析到新节点。

理由：展示层去重满足蓝图“多条候选推荐同一路径合并为一条节点建议”；后端同名复用提供最终去重保障。

### D6：迁移

一个 Alembic 迁移为 `candidates` 增加上述三个可空列，无回填；回滚即删列。与上一 change 的可空推荐字段迁移方式一致。

## Risks / Trade-offs

- [路由 Agent 输出多余字段或非法父节点] → 应用层仅接受 `no_suitable` 的新节点建议，并校验父节点属于当前项目；非法值丢弃或降级为空。
- [同名节点判断受大小写/空白影响] → 应用层先 `strip` 再 `casefold` 比较，保证“使用与维护”和“ 使用与维护 ”不重复建节点。
- [原子操作中途失败] → 提交前抛异常，由会话回滚；新增后端测试覆盖非法父节点和同名复用，保证不落半成品。
- [创建节点后前端缓存旧目录树] → mutation 显式失效 `projectTree` 与候选相关查询，成功后立即刷新。
- [本轮不处理批量场景] → 去重展示仅限当前 Source；跨 Source 去重留给后续 `add-batch-candidate-review`。

## Migration Plan

1. 新增 Alembic 迁移，为 `candidates` 增加 `new_node_name`、`new_node_parent_id`、`new_node_reason` 可空列。
2. 开发环境执行 `alembic upgrade head`。
3. 回滚策略：删除该迁移并回退对应代码；新列可空，不影响旧候选数据。

## Open Questions

- 手动修改来源项目触发的重路由是否会同时清理旧的新节点建议：实施时按现有 `clear_candidate_routing` 一并清理，避免旧项目建议残留。
- `new_node_parent_id` 是否需要在 `no_suitable` 分支之外的 `needs_review` 中保留：本轮只落库 `no_suitable`，后续按真实使用再评估。
