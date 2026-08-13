## Context

Source/Attachment 采集已落地，但 Source 目前没有处理状态，也没有可观察、可重试的任务对象。本 change 搭处理管道骨架：把「任务状态机、异步执行、失败重试、Provider 边界」先做通，真正 OCR/解析/候选由 `add-organizing-agent-extraction` 接入。

当前 AI 侧只有文本 `AIProvider.complete()`（Demo 确定性、deepseek/豆包为未接入桩），不适用于「处理一个 Source」这件事，因此需要独立的处理 Provider 抽象。

## Goals / Non-Goals

**Goals:**

- 新增 `ProcessingTask` 模型与 Source 处理状态。
- 用进程内异步 Worker 跑通「等待处理 → 处理中 → 已完成 / 失败」状态机。
- 建立 `ProcessingProvider` 边界：Demo 确定性实现，真实 Provider 留桩。
- 支持失败重试与幂等，不复制 Source。

**Non-Goals:**

- 不实现 OCR、语义拆分、候选生成。
- 不实现 Project Context Snapshot。
- 不引入独立任务队列。
- 不自动触发处理。

## Decisions

### D1：ProcessingTask 独立表，Source.status 为派生展示

新增 `processing_tasks` 表：`source_id`（唯一外键）、`status`、`step`、`error`、`retry_count`、时间。`Source.status` 作为冗余字段，由 Worker 在任务状态变化时同步更新，便于列表快速展示。一个 Source 当前只有一个处理任务，重试复用同一任务记录并递增 `retry_count`，不复制 Source。

### D2：进程内常驻 asyncio Worker

通过 FastAPI `lifespan` 在应用启动时启动一个后台 asyncio 循环，周期性从数据库领取 `等待处理` 任务执行；应用关闭时取消该任务。领取用「条件更新」实现原子认领（`status='waiting' → 'processing'`），避免并发重复执行。SQLite 单 Worker 场景足够；后续有真实并发/多实例再迁独立队列。

### D3：ProcessingProvider 与文本 AIProvider 解耦

新增 `ProcessingProvider` 抽象，负责「处理一个 Source」：Demo 实现做确定性短暂延迟后成功；真实 Provider 先留桩，调用时抛 `NotImplementedError`。这与现有文本 `AIProvider.complete()` 分离，符合蓝图「文本 Agent 与视觉解析解耦」。

### D4：状态机与幂等

状态集合：`waiting / processing / done / failed`。触发处理时创建或复位任务为 `waiting`；Worker 认领后置 `processing`；成功置 `done`，失败置 `failed` 并记录 `step` 与 `error`。重试把 `failed → waiting` 并 `retry_count += 1`。`processing` 状态下再次触发直接忽略或返回冲突，不产生重复执行。

### D5：手动触发

采集后 Source 保持 `waiting`，不自动处理。来源列表对 `waiting` 显示「开始处理」，对 `failed` 显示「重试」，分别调用触发接口。接口只负责把任务置为待处理，实际执行由 Worker 异步完成。

### D6：测试策略

Demo Provider 延迟极短；Worker 的领取与状态流转逻辑拆成可独立调用的函数，测试直接触发并轮询状态，避免依赖真实等待时长。异步 Worker 的启动/关闭通过 lifespan 测试覆盖。

## Risks / Trade-offs

- [进程内 Worker 与应用同生命周期，进程重启会中断处理] → 任务状态持久化在数据库，重启后 Worker 继续领取 `waiting/processing` 遗留任务；对 `processing` 遗留任务做超时复位或标记失败，避免永久卡住。
- [SQLite 并发写入] → 单 Worker + 条件更新认领，控制并发为 1。
- [真实 Provider 尚未接入导致处理永远失败] → 桩实现明确报错，UI 展示失败并可重试，不静默成功。

## Migration Plan

新增 Alembic 迁移：

- `sources` 增加 `status` 列（默认 `waiting`）；
- 创建 `processing_tasks` 表：`id`、`source_id`（唯一外键，ondelete CASCADE）、`status`、`step`、`error`、`retry_count`、`created_at`、`updated_at`。

## Open Questions

- 处理中的任务超时阈值（后续实现时给出默认值）。
- Demo 处理器的延迟时长（便于观察「处理中」即可，取一个很短的值）。
