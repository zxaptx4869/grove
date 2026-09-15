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
- 不在本 change 接入前端页面或移动端。

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

## Risks / Trade-offs

- [持久化字段不足] → 先使用现有 Conversation/Message/Run 模型；只有无法恢复 Workspace、任务范围或状态时才提出最小字段变更，不复制实验 JSON。
- [实验循环假设单活动轮次] → 适配器在提交前执行 Conversation 活动 Run 的幂等和并发检查，并复用正式取消边界。
- [正式 API 与实验台结果合同不同] → 以结构化块转换器作为唯一边界，并为每种块和终态添加确定性测试。
- [旧执行图残留调用] → 为 Web 新入口添加执行链路标记和测试断言，确保一次请求只出现统一循环调用。
