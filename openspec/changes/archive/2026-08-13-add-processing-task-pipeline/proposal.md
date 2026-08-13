## Why

采集能力已经落地（Source/Attachment），但采集后的材料只是躺在列表里，缺少「处理」这一环。后续 OCR、语义拆分与候选生成（`add-organizing-agent-extraction`）需要一个可观察、可重试、幂等的任务管道来承载。先把管道骨架跑通，避免后续把「任务执行、状态、失败重试」和「解析逻辑」混在一起。

## What Changes

- 新增 `processing-task` 能力：
  - `ProcessingTask` 模型：归属 Source，记录状态、步骤、错误与重试次数；
  - 状态机：等待处理 → 处理中 → 已完成 / 失败，失败可重试；
  - 进程内异步 Worker：应用启动后轮询「等待处理」任务并执行；
  - Provider 边界：`ProcessingProvider` 抽象，Demo 确定性实现，真实 Provider 留桩。
- 修改 `source-management`：
  - `Source` 增加处理状态（等待处理 / 处理中 / 已完成 / 失败）；
  - 采集后默认「等待处理」，不自动处理；
  - 来源列表展示状态，并提供「开始处理」（等待处理）/「重试」（失败）按钮。

## Capabilities

### New Capabilities

- `processing-task`: ProcessingTask 模型、状态机、异步 Worker、处理 Provider 边界与幂等重试。

### Modified Capabilities

- `source-management`: Source 处理状态字段与「开始处理 / 重试」触发语义。

## Impact

- 后端：新增 ProcessingTask 模型与迁移、ProcessingProvider 抽象（Demo + 桩）、FastAPI lifespan 异步 Worker、触发与状态 API；Source 模型增加状态字段。
- 前端：来源列表展示处理状态，增加「开始处理 / 重试」操作。
- 配置：处理 Provider 标识（demo 默认）。
- 无外部服务依赖；本轮不接真实 OCR 或 Agent。

## Non-Goals

- 不做 OCR、语义拆分与候选生成（留给 `add-organizing-agent-extraction`）。
- 不做 Project Context Snapshot（留给 `add-project-context-snapshot`）。
- 不做确认台与 Entry 归档（留给后续 change）。
- 不引入独立任务队列（Celery/RQ/Redis）。
- 不自动触发处理（保留「开始处理」按钮）。
- 不接入真实 Provider（仅留桩，调用时明确报未接入）。
