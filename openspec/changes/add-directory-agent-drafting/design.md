## Context

知识空间已有完整的手动目录管理（Node 树、增删改移排、Workspace 校验），前端“与 AI 共创目录”目前只是占位弹层。Project Context Snapshot 已增强并暴露公共接口，可作为 Directory Agent 的输入。蓝图要求 AI 目录输出始终进入 Directory Draft，确认前不触碰正式 Node。

参考旧项目 KnowStruct 的成熟做法：澄清问题一次给一批（选项 + 自由输入）、草稿有状态机与规范化草稿节点表。本 change 采用该模式并适配 Grove 的 BigInt + async SQLAlchemy 技术栈。

## Goals / Non-Goals

**Goals:**

- Directory Agent 从零起草目录，先问卷式澄清（一次 3–5 题，批次上限 2），再生成候选树。
- 可视化候选树 + 内联编辑（增/删/改名/改说明）。
- 用户确认后校验并原子应用为正式节点，触发项目上下文刷新。
- 记录生成来源（provider / model / is_fallback），防静默降级。

**Non-Goals:**

- 节点拓展（`add-directory-agent-node-expansion`）、对话式调整草稿、思维导图、语义检索、流式输出。
- 自动应用草稿；不修改正式 Node 模型；不做跨项目草稿与草稿历史。

## Decisions

### D1：Directory Draft 数据模型

新增两张表：

```text
directory_drafts
├── id / project_id（每项目一份活跃草稿）
├── status：drafting / awaiting_input / pending_confirm / confirmed / discarded
├── next_action：clarify / generate
├── clarify_batches：已用澄清批次（0/1/2）
├── clarify_json / clarify_answers_json
├── provider / model / is_fallback
└── created_at / updated_at

directory_draft_nodes
├── draft_id / parent_id（草稿内自引用，可空表示根）
├── name / description / position
└── created_at / updated_at
```

理由：规范化草稿节点比 JSON 树更适合内联编辑、校验与确认应用；参照 KnowStruct 已被验证的模型，但用现有 BigInt 风格。

### D2：状态机

```text
drafting → awaiting_input（有澄清问题）→ drafting → pending_confirm（候选树）
                                                     → confirmed（应用）/ discarded（丢弃）
```

`next_action = clarify` 时返回问题并等待输入；`generate` 时生成树。失败保留 `last_error`，可重试。

### D3：问卷式澄清

Agent 一次输出 3–5 道结构化问题：`{id, text, options, multiple}`。用户一次提交 `answers: {qid: string | string[]}`，支持点选或自由输入。`clarify_batches` 达到 2 后强制生成候选树，不再提问。

理由：比逐轮一问成本低、体验好；旧项目已验证该模式。

### D4：Directory Agent

新增 `agents/directory.py`：

- `run_directory_clarify(db, workspace_id, project, context_snapshot, answers)` → `ClarifyResult`（needs_more + questions）；
- `run_directory_draft(db, workspace_id, project, context_snapshot, answers)` → 候选树草稿；
- 输入：项目说明 + Project Context 快照（公共接口）+ 用户答案；
- 无密钥/TestModel 时确定性兜底（如按项目名生成两级树）；
- 返回 GenerationMeta（provider / model / is_fallback），沿用防静默降级约定。

### D5：API

```text
POST   /api/projects/{id}/directory-draft          创建或复用活跃草稿
GET    /api/projects/{id}/directory-draft          读取草稿（含问题/节点/来源）
POST   /api/projects/{id}/directory-draft/clarify  提交澄清答案
PATCH  /api/projects/{id}/directory-draft/nodes    全量提交编辑后的草稿节点
POST   /api/projects/{id}/directory-draft/apply    确认应用
POST   /api/projects/{id}/directory-draft/discard  丢弃
```

内联编辑采用“前端持有整棵草稿树，PATCH 全量替换”，避免增量操作的并发复杂度。

### D6：确认应用与原子性

`apply` 流程：

1. 校验草稿为 `pending_confirm`；
2. 构建草稿树：parent 引用合法、无环、名称长度 ≤128、节点总数 ≤200；
3. 从根到叶按 position 顺序创建正式 Node（复用现有节点创建/位置计算逻辑）；
4. 同一事务内完成，任一失败整体回滚；
5. 成功后草稿标记 `confirmed`，调用 `schedule_refresh(project_id, "directory_changed")`。

空目录起始是本 change 的主要场景；非空项目入口允许打开工作区，但应用时若项目已有正式节点则要求用户明确“重建”，否则拒绝，防止误覆盖。

### D7：前端目录共创工作区

替换 `ProjectPage` 占位弹层为独立工作区：

- 问卷视图：一次展示全部澄清问题，选项 + 自由输入，一次提交；
- 候选树视图：层级展示草稿节点，支持内联新增/改名/改说明/删除；
- 应用确认：展示将创建节点数与受影响 Entry（从零为 0），确认后调用 apply；
- 入口：空目录内容区与知识空间页头。

### D8：生成来源展示

草稿响应携带 `provider / model / is_fallback`，前端展示“真实模型 / 离线生成”徽标；降级时后端 warning 日志。

## Risks / Trade-offs

- [前端持有整棵树全量提交可能覆盖他人编辑] → 个人知识库单用户场景可接受；PATCH 前校验草稿 `updated_at` 防覆盖。
- [大草稿 token 与节点上限] → 澄清批次 2 + 节点上限 200 控制；上限按真实使用校准。
- [应用中途失败留半成品] → 同一事务原子创建，失败整体回滚。
- [旧草稿长期滞留] → 每项目一份活跃草稿，新起草覆盖旧草稿；提供 discard。
- [模型输出非法树结构] → 应用层校验 parent/环/长度/上限，非法直接拒绝。

## Migration Plan

一个 Alembic 迁移创建 `directory_drafts` 与 `directory_draft_nodes` 两张表；无回填，正式 `nodes` 表不变。回滚即删两表。

## Open Questions

- 节点上限 200 与澄清批次 2 为初始默认，按真实使用校准。
- 内联编辑暂不含“移动节点”，后续按需补充。
