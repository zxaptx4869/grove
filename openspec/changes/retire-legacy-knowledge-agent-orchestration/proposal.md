## Why

正式 Web 与实验台都已统一使用 `dialogue_loop`，但旧 Knowledge Agent 的 quick / investigate / composite / coverage 执行器仍留在正式代码中，且取消能力仍由正式服务反向依赖旧 `runner`。这既扩大维护与测试面，也使旧执行快照可能在 Worker 恢复时被错误送入新循环，因此需要在不改变现行 Agent 合同的前提下完成退役。

## What Changes

- **BREAKING**：移除旧 Knowledge Agent answer 执行入口及仅服务于该入口的调查、多级规划、复合回答、共享执行图和覆盖补查实现；旧执行器不再作为回滚路径。
- 将 `RunCancelled` 与 Run 取消检查迁入独立公共模块，Candidate、Entry Revision、只读搜索、Worker 与 `production_adapter` 继续保持原有取消语义。
- 收紧 Worker 的历史 Run 恢复边界：只恢复当前 operation Run 或统一 dialogue-loop 可安全重试的状态；旧执行步骤明确失败收尾，不进入新循环。
- 迁移仍覆盖现行合同的测试夹具，删除只验证已退役执行图的测试；保留取消、重试、幂等、Workspace、权限、候选确认与 Entry Revision 的验证意图。
- 保留旧数据库字段、表、Alembic 历史迁移以及 API 所需的历史结果/调查兼容投影，不清理历史数据。
- 不改变正式 API、统一 `dialogue_loop`、`production_adapter`、实验台、模型、提示词、预算、工具合同、候选边界或移动端代码。

## Capabilities

### New Capabilities

- 无。

### Modified Capabilities

- `knowledge-agent-run`：普通 answer Run 只允许统一 dialogue-loop；取消控制从旧执行器解耦；旧执行步骤不得被恢复到新循环。
- `knowledge-agent-dialogue-loop-production-adapter`：补充旧执行快照的拒绝恢复边界，并明确正式调用链不得依赖旧 runner。
- `knowledge-agent-investigation`：退役旧 answer 模式下的独立 investigation 执行器。
- `knowledge-agent-investigation-ledger`：停止创建和恢复旧 investigation 执行账本，但保留历史详情只读兼容。
- `knowledge-agent-composite-answer-planning`：退役旧 answer 的复合计划与串行执行合同，保留历史字段投影。
- `knowledge-agent-bounded-coverage-repair`：退役旧 answer 的覆盖补查执行合同，保留历史字段。
- `knowledge-agent-shared-execution-graph`：退役旧 answer 的共享执行图与恢复合同，保留历史字段。

## Impact

- 后端：`knowledge_agent_worker`、`production_adapter`、Candidate、Entry Revision、搜索服务、dialogue-loop 预检/插桩及旧编排模块。
- 测试：现行 Web/Worker/operation Run 测试改用统一循环边界；旧 runner、investigation、composite、coverage、shared graph 专属测试退出。
- 数据与 API：不做数据库迁移，不删除历史字段、调查表或公开响应字段；历史 Run 仍可读取，但不能恢复执行。
- 客户端与部署：Web、实验台和移动端合同不变；本 change 不涉及阿里云部署。
