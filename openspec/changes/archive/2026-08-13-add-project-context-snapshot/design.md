## Context

当前后端已有 Project/Node/Source/ProcessingTask 与文本 `AIProvider`（Demo + 未接入桩）以及处理 `ProcessingProvider`（Demo + 未接入桩）两套 Provider 抽象。项目上下文尚未建模，项目首页只展示项目说明与目录概览，没有可供后续 Agent 共享的派生上下文。

本 change 落地 Project Context Snapshot 初始版本：只使用项目说明与正式目录节点生成初始概要，不依赖尚未实现的 Entry 或 Candidate；已确认 Entry、知识覆盖、近期主题与上下文版本留给 `enhance-project-context-with-entries`。

## Goals / Non-Goals

**Goals:**

- 新增 `ProjectContext` 模型与 `project-context` 能力，每个 Project 至多一份快照并按 Workspace 隔离。
- 用独立的 `ProjectContextGenerator` 抽象（Demo 确定性 + 未接入桩）生成项目概要、当前关注方向与目录主题。
- 实现更新触发、防抖、异步刷新与失败回退。
- 提供查看、纠正与手动重新生成的 API 与项目首页展示。
- 提供可复用的 Agent 公共上下文接口。

**Non-Goals:**

- 不纳入 Entry、知识覆盖、近期主题或上下文版本。
- 不接入 PydanticAI、Organizing/Directory/Reader/Discovery Agent。
- 不引入独立任务队列。
- 不把上下文写入正式 Entry 或正式目录。

## Decisions

### D1：ProjectContext 单表，effective 值由生成结果与纠正合并

新增 `project_contexts` 表，字段为 `project_id`（唯一外键）、`project_summary`、`current_focus`、`directory_topics`（JSON 字符串数组）、`status`（pending/ready/failed）、`error`、`generated_at`、`refresh_due_at`、`updated_at`。

- 项目说明原文不在快照表复制，读取时从 `Project.description` 组装，保证用户说明始终是权威源。
- 生命周期状态从 `Project.status` 组装，不复制，避免双写不一致。
- `directory_topics` 以 JSON 数组保存，便于前端结构化渲染。

### D2：独立 ProjectContextGenerator，与文本 AIProvider 解耦

沿用 `ProcessingProvider` 的边界模式，新增 `ProjectContextGenerator` 抽象：

- Demo 实现确定性：项目概要围绕项目说明与节点数量生成，目录主题取正式目录节点名列表，纠正字段优先于默认生成。
- 真实 Provider 留桩，调用时明确抛 `NotImplementedError`。
- 生成器输入是 `Project`、正式 `Node` 列表与用户纠正，不接收 Candidate/Entry。

这样避免依赖文本 `AIProvider.complete()` 的非结构化 Demo 输出，同时保持「离线确定性测试」能力。

### D3：持久化 `refresh_due_at` 实现防抖与异步刷新

项目说明或目录变化时，只把 `refresh_due_at` 置为「当前时间 + 防抖时长」，不阻塞原请求；同一项目在窗口内再次变化会重置 `refresh_due_at`，自然合并为一次刷新。

进程内异步 Context Worker 在应用启动后轮询 `refresh_due_at <= now` 的行，并用条件更新（`refresh_due_at IS NOT NULL → NULL`）原子认领，避免并发重复生成；认领后执行生成并写回。这样防抖状态持久化，进程重启后仍可继续处理遗留的到期刷新。

### D4：失败回退语义

生成成功时覆盖生成字段并置 `status=ready`、清空 `error`。生成失败时：

- 若 `status=ready` 且已有 `project_summary`，保留上一份生成内容，仍置 `status=ready`，写入 `error` 供前端提示「更新失败，当前展示上一份快照」；
- 若尚无有效快照，置 `status=failed` 并写入 `error`。

### D5：纠正作为覆盖 + 高优先级约束

`user_corrections` 保存用户对 `project_summary` 与 `current_focus` 的可选覆盖（JSON 部分对象）。读取时覆盖优先于生成字段；`POST /refresh` 重新生成时把纠正传入生成器作为约束，Demo 生成器直接采用纠正字段，真实 Provider 在提示词中优先遵循纠正。

本轮只纠正 AI 生成的项目概要与当前关注方向；目录主题由正式目录决定，用户应通过编辑目录来纠正它。

### D6：API 与公共上下文接口

- `GET /api/projects/{project_id}/context`：返回结构化快照，不存在时按 `pending` 处理并惰性建行。
- `PATCH /api/projects/{project_id}/context`：保存纠正并安排刷新。
- `POST /api/projects/{project_id}/context/refresh`：手动重新生成（同步执行，便于即时反馈与测试）。
- 服务层 `get_project_context_out(...)` 即后续 Agent 的公共上下文接口，Agent 不直接读表。

### D7：触发点

在以下位置调用 `schedule_refresh`：

- 创建项目（初始生成）；
- 更新项目说明（`rename_project` 中 description 变化）；
- 创建 / 更新 / 移动 / 删除 / 排序目录节点。

生命周期状态变化不需要重新生成，因为状态从 `Project.status` 实时组装。

### D8：测试策略

- 后端测试环境关闭 Context Worker（沿用 conftest 设置），直接调用服务函数或手动 `POST /refresh` 验证生成与回退；
- Worker 领取逻辑通过把 `refresh_due_at` 手动置为过去时间后调用领取函数验证；
- Demo 生成器确定性输出可直接断言。

## Risks / Trade-offs

- [进程内 Worker 与应用同生命周期，重启可能中断刷新] → `refresh_due_at` 持久化，重启后继续领取到期刷新。
- [SQLite 并发写入] → 单 Worker + 条件更新认领，控制并发为 1。
- [真实 Provider 尚未接入导致生成失败] → 桩实现明确报错，失败回退保留上一份有效快照或标记失败，不静默成功。
- [纠正字段语义] → 本轮只覆盖项目概要与当前关注方向，目录主题不提供独立纠正，避免与正式目录冲突。

## Migration Plan

新增 Alembic 迁移创建 `project_contexts` 表：

- `id`（主键）；
- `project_id`（唯一外键，ondelete CASCADE）；
- `project_summary`、`current_focus`、`directory_topics`、`user_corrections`（Text，可空）；
- `status`（默认 `pending`）、`error`（Text，可空）；
- `generated_at`、`refresh_due_at`（DateTime，可空）；
- `updated_at`（server_default + onupdate）。

不对现有项目做数据回填，读取时惰性建行并安排初始刷新。

## Open Questions

- 防抖时长的默认值（先取短值便于验收，真实使用后按「项目上下文快照的更新频率」问题调整）。
- 真实生成 Provider 与 PydanticAI 的接入边界（留给后续 Agent change）。
