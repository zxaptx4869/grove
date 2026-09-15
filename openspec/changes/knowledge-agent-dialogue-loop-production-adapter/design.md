## Context

实验台 `evals.dialogue_loop` 已直接复用 Grove 的只读领域工具和 Workspace 边界，但以进程内 `LoopState`、本地工作台 JSON 和实验记录为外壳。正式 API 已有 Conversation、Message、Run、Context Version、鉴权和持久化，却仍由 `runner.py` 驱动 context decision、basis、result mode、answer mode 和 composite answer 等多级执行图。两条链路同时存在，是之前 Web 迁移不一致的根因。

## Goals / Non-Goals

**Goals:**

- 让正式 Web Agent 只调用一次统一循环作为对话编排核心。
- 复用正式会话与运行持久化，使轮次可查询、可取消、可审计，并在允许范围内恢复 continuation。
- 保持 Workspace、用户、项目、目录、Entry、Source 和候选稿校验由正式服务完成。
- 输出稳定的结构化回答块和精确轮次状态。

**Non-Goals:**

- 不把实验台运行时直接作为生产服务依赖。
- 不保留旧多级规划链作为同请求的隐式 fallback。
- 不接入移动端页面；本阶段 Web 只实现 Grove 桌面应用壳内的薄展示层。

## Decisions

### 1. 统一循环作为 Web 唯一编排入口

新增生产适配器调用 `build_agent`/`run_turn` 所需的最小核心能力；Web 请求不得先经过旧 `runner.py` 的多级规划阶段。旧执行图底层的鉴权、领域工具、结果持久化辅助函数可以继续复用，但不再作为本入口的 Agent 编排器。

### 2. 正式状态包裹实验状态

每轮开始时由正式 Conversation、历史 Message、当前用户、Workspace 和授权范围构造 `LoopState`。循环完成后只把面向生产所需的回答、工具/模型可观测记录、状态、结果句柄元数据和 continuation 摘要写回正式模型；实验台的完整调试 JSON 不成为 API 合同。

### 3. 结果类型由程序保真映射

适配器保留 `text`、`list`、`statistic`、`entry`、`evidence`、`candidate`、`insufficient` 等块的真实类型，前端不根据句柄或标题猜测类型。`completed`、`partial_completed`、`not_executed`、`unsupported`、`failed` 和 `can_continue` 由程序状态决定。

### 4. 失败与恢复采用最小可恢复状态

成功工具结果不因收尾失败而丢失；continuation 只保存下一步所需的授权结果、任务类型、范围和校验引用。恢复时重新校验 Workspace、用户和对象归属，只重试未完成步骤，不重复成功查询。无法安全恢复时返回明确失败状态。

### 5. 分阶段切换与回滚

先以新适配器提供受控 Web Agent 入口，完成 API 短链路验证后再接页面。旧入口保留到人工验收完成；不得在同一请求中双跑或根据失败静默切回旧编排。回滚通过恢复 Web 路由到旧入口完成，不改实验台核心。

### 6. 实施盘点后的最小持久化调整

盘点确认现有 `KnowledgeAgentRun` 只有旧回答 JSON 和旧执行图快照字段，无法同时保存统一循环的结构化 blocks、终态、可继续标记以及恢复最终步骤所需的有界材料。复用 `answer_json` 会破坏旧 API 的 `KnowledgeAnswerOut` 合同，复用实验台 JSON 或任务状态也会把调试格式变成正式格式。因此增加一个可空的 `dialogue_loop_state_json` TEXT 字段，仅保存生产适配器的版本化、有界快照；旧 Run 保持 NULL，不回填、不改变旧字段语义。

该字段是 continuation 跨服务重启安全恢复所需的最小迁移，迁移编号为 `fd4e5f6a7b8c`，不新增任何 Entry、Source 或权限字段。

### 7. 可观测结果分类与历史 Run 收尾

模型调用审计在保留原有 `is_fallback` 字段的同时增加 `outcome`：
`model_success`、`not_dispatched`、`deterministic_fallback`、`offline_test_model` 和
`model_call_failed`。预算停止点产生的未派发请求仍记录原因，但不把真实模型已成功完成的阶段标记为 fallback。

Worker 将 `processing` 且缺少 `claimed_at` 的历史 Run 视为不可安全恢复，明确标记 `failed` 并释放活动槽；
该路径不重新执行旧规划图、模型或工具，也不修改正式 Entry。

### 8. Grove Web 薄壳接入

Web 页面复用现有 AppShell，在全局导航增加知识 Agent 入口；页面内部只保留会话列表和对话区，不再渲染实验台右侧运行状态栏。会话、消息、Run、取消和可观测记录全部通过正式 `/api/knowledge-agent` 接口读取，前端不持有实验台进程内状态，也不解析实验台 JSON。

消息按正式 API 返回的消息 ID 和 Run ID 去重。轮询只刷新活动 Run，终态后读取最新消息、`dialogue_blocks` 和 observability；结构化块由 `kind` 与结果语义直接映射到展示组件。`can_continue` 只显示“继续”操作，点击后提交普通正式消息，由后端恢复 continuation。

## Risks / Trade-offs

- [持久化字段不足] → 已确认无法在不污染旧合同的前提下复用现有字段，采用 `dialogue_loop_state_json` 最小快照迁移，不复制实验 JSON。
- [实验循环假设单活动轮次] → 适配器在提交前执行 Conversation 活动 Run 的幂等和并发检查，并复用正式取消边界。
- [正式 API 与实验台结果合同不同] → 以结构化块转换器作为唯一边界，并为每种块和终态添加确定性测试。
- [旧执行图残留调用] → 为 Web 新入口添加执行链路标记和测试断言，确保一次请求只出现统一循环调用。
