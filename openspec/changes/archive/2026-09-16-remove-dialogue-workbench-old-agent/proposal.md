## Why

实验台仍保留旧 Agent 与统一 dialogue-loop 的 old/new 对照编排，其中 old 臂会调用已经退役的 `runner.execute_run()`。正式 Web 与实验台的新流程已经共享统一 dialogue-loop，继续保留旧臂只增加执行、报告和测试维护成本，也容易让后续验证误把旧编排当作可用入口。

## What Changes

- 实验台只运行统一 dialogue-loop，移除 old/new 对照选择、old 臂启动和 `runner.execute_run()` 执行路径。
- 移除实验台仅用于 old/new 对照的 CLI 参数、双副本调度、双臂资源汇总、旧流程报告区块和对照专用测试。
- 保留实验台现有统一循环对话、隔离快照、真实模型验证、预算审计、诊断、记录和导出能力。
- 保留 `runner.py`、调查、coverage repair、composite、旧迁移字段及其历史兼容能力；不改变正式 Web Agent 执行链。
- 记录并验证移动端继续使用统一 `/api/knowledge-agent` 接口，本次不实施移动端迁移。

## Capabilities

### New Capabilities

- `knowledge-agent-dialogue-workbench-unified`: 实验台只提供统一 dialogue-loop 流程及其验证、记录和导出能力。

### Modified Capabilities

- 无。正式 Web Agent、移动端 API 和统一 dialogue-loop 核心规格的行为合同不变。

## Impact

- 代码：`backend/evals/dialogue_loop/` 的实验编排、报告和入口，以及对应实验台/对照测试；不修改 `backend/evals/dialogue_loop/loop.py` 核心循环。
- 测试：删除或改写只验证 old/new 对照的测试，保留统一循环、工作台、生产适配器和 Web Agent 测试。
- 接口：不改变正式 `/api/knowledge-agent` API、Worker、production adapter、Candidate、Entry Revision 或移动端接口。
- 数据：不新增、不删除、不迁移数据库字段，不清理历史数据。
