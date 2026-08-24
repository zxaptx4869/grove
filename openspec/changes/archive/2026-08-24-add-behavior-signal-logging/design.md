## Context

P0-B 收口项：为「AI 推荐 → 用户决定」链路建立长期信号记录。系统已具备项目推荐、目录推荐、关系建议与批量操作，且 AI 推荐值散落在现有表，但编辑会覆盖 AI 原值、批量路径不落对比，需要独立表在决定时刻记录。

## Goals / Non-Goals

**Goals:**

- 记录四类推荐信号（项目 / 目录 / 内容编辑 / 关系建议），批量操作逐条落同类信号；
- 提供接受度判定（接受 / 修改 / 拒绝）；
- 提供按 Workspace 隔离的只读查询接口；
- 删除业务对象后信号保留。

**Non-Goals:**

- 不做统计面板、分析 UI 与个性化算法；
- 不记录浏览、搜索等非决策行为；
- 不改变现有业务接口语义，不新增前端埋点。

## Decisions

### D1：信号表结构

`behavior_signals`：

| 字段 | 说明 |
|---|---|
| workspace_id | 非空，Workspace 隔离 |
| user_id | 空，外键置空保留 |
| project_id / source_id / candidate_id | 空，外键置空保留 |
| signal_type | `project_decision` / `node_decision` / `content_edit` / `relation_decision` |
| recommended / final | JSON 快照（Text），推荐值 vs 最终值 |
| accepted | 布尔可空；`content_edit` 与无推荐时为 null |
| detail | 可空说明（如理由、新建节点名） |
| created_at | 记录时间 |

### D2：埋点位置

| 信号 | 位置 |
|---|---|
| project_decision | `sources.update_source` 修改项目归属时 |
| node_decision | `entry.archive_candidate`、`archive_candidate_with_new_node`；`candidate_review.batch_decide_project_candidates`（拒绝）、`batch_update_candidates_directory` |
| content_edit | `candidate_review.edit_candidate`（仅实际修改字段） |
| relation_decision | `entry.add_evidence_to_entry`、`apply_revision_to_entry` |

### D3：写入与事务

`record_behavior_signal(db, *, workspace_id, user_id, signal_type, recommended, final, accepted, detail, project_id, source_id, candidate_id)` 仅 `db.add` + `flush`，跟随业务事务提交或回滚，保证「业务动作 + 信号」原子一致，不丢信号。

### D4：接受度判定

`project_decision`：最终项目 == 推荐项目（均非空）→ true；不同或保持未归属 → false；无推荐 → null。`node_decision`：最终节点 == 推荐节点 → true；不同 / 拒绝（无节点）/ 新建节点（推荐为空）→ false 或 null（新建且推荐为空时记录 detail）。`relation_decision`：执行动作与建议一致 → true。`content_edit` 恒为 null。

### D5：user_id 传递

API 层增加 `CurrentUser` 依赖，将当前用户 id 传入 service；不通过 Workspace 推断，避免多成员时混淆。

### D6：只读接口

`GET /api/behavior-signals`：按 Workspace 过滤，支持 `signal_type`、`project_id` 过滤与分页；只读，无写端点。

## Risks / Trade-offs

- [信号写入成为业务事务新失败点] → 写入为单次 insert，风险低；与业务同事务保证不丢信号，宁可业务失败也不静默缺信号。
- [快照冗余] → 推荐/最终值以 JSON 文本快照存储，牺牲一点冗余换取事后可分析性与不受业务表覆盖影响。

## Migration Plan

新增 `behavior_signals` 表（Alembic 迁移），无数据回填、无破坏性变更。

## Open Questions

- 无。
