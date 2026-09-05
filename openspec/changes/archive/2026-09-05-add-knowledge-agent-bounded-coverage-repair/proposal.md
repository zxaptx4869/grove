## Why

首次复合计划和共享执行图已能生成可核验的逐项 coverage，但当某项回答义务仍为 `insufficient` 或 `partial` 时，quick Run 只能直接以缺口收尾，不能利用已得结果做一次针对性补查。现在已有固定首次计划、细粒度节点结果和恢复检查点，可以在不引入通用 Agent loop 的前提下安全补齐这个纵向闭环。

## What Changes

- 修复手动验收发现的兼容缺陷：自动路由识别复合 quick 能力，部分回答与依据表达一致，综合去重并绑定义务，补查统计保持结构化过滤口径，失败时展示确定性新事实与明确警告。

- quick 复合回答首次综合后，由服务端从真实逐项 coverage 中筛选可修复的 `insufficient/partial` 义务；已回答、执行失败、纯模型漏答和当前无外部工具可满足的义务不发起工具补查。
- 模型最多提出一份只引用原回答义务的补查候选；服务端严格校验目标义务、闭合只读工具、重复请求、依据边界和固化预算，不允许补查新增或改写首次义务与计划。
- 为一次补查固化特性开关、查询数、节点数、工具调用、Entry、Evidence、耗时、图与状态 JSON 字节上限；达到上限、无新查询或重复已完成请求时确定性停止。
- 复用同 Run 已提交的首次 node/result/Evidence，不重放已完成节点；串行和共享图路径都只执行经验证的新增请求。
- 持久化首次合法回答/覆盖、补查计划、冻结预算、节点终态和停止原因；在取消、Worker 租约恢复、幂等重试和部署配置变化后仍沿用原决策。
- 补查成功后仅在合法新依据上重新综合并重算 coverage、answer basis、Citation 和终态；补查计划、工具或综合失败时保留首次合法结果，同时显式记录 partial/insufficient、剩余缺口与 fallback。
- 保持现有公开 API、原生端投影和旧 Run 兼容，新增状态只作为服务端内部恢复与审计依据。

### Non-Goals

- 不实现第二次以上补查、无限循环、通用 B2 Agent loop，不迁移 quick/investigate/entries 既有 Workflow。
- 不允许补查改写首次计划、扩大 Workspace/项目范围、调用未知工具或接入外部搜索。
- 不做 Operation Plan、`prepare_operation`、知识写入或事实工作集推进；不创建或修改 Entry、Source、Candidate、Draft、Extraction 或目录。
- 不新增公开补查操作按钮、原生端必填字段或破坏性 API 变更。

## Capabilities

### New Capabilities

- `knowledge-agent-bounded-coverage-repair`: 定义 quick 复合回答的一次有界缺口补查、候选计划校验、结果复用、停止、恢复、取消、可观测和无写入副作用边界。

### Modified Capabilities

- `knowledge-agent-composite-answer-planning`: 首次逐项 coverage 成为补查准入事实，终态综合可在一次受控补查后重算，但首次计划和合法结果不变。
- `knowledge-agent-shared-execution-graph`: 共享图提供同 Run 已提交 node/result/Evidence 的恢复与复用基础，补查只追加并执行严格新增的有界只读节点。
- `knowledge-agent-run`: Run 在一次补查的覆盖检查、规划、执行和终态边界上增加检查点，并保持取消、租约恢复、幂等和旧协议兼容。

## Impact

- 后端：Knowledge Agent 复合回答候选模型、覆盖派生、串行/共享图执行、Runner、可观测、Run 持久化和 Alembic 迁移。
- 配置：新增默认关闭的补查开关及查询、节点、工具、Entry、Evidence、耗时和 JSON 字节预算。
- 协议：继续返回现有 answer/points/Citation/coverage/gaps/basis/fallback；不向旧客户端暴露内部补查计划、查询、节点、范围或指纹。
- 测试：增加串行/共享图等价、缺口准入、重复调用拒绝、失败保底、预算、取消、恢复、Workspace/项目隔离和无写入副作用评估。
