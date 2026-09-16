## Context

当前普通 answer Run 的唯一正式链路已经是 `Worker → production_adapter → evals.dialogue_loop`，实验台也只运行同一循环。旧 `runner` 及其 investigation、composite、coverage、shared graph 依赖不再承接正式请求，但 `RunCancelled` 和取消检查仍由 Worker、`production_adapter`、Candidate、Entry Revision 与搜索服务从 `runner` 导入；dialogue-loop 的预检和插桩还动态导入部分旧 Agent 模块。

数据库仍保存旧执行快照、调查账本和结果形态字段，API 也继续投影历史 Run。退役必须切断执行依赖，而不能破坏历史读取或当前 operation Run。

## Goals / Non-Goals

**Goals:**

- 正式 answer、Candidate、Entry Revision 与搜索路径不再导入旧 `runner`。
- 删除只服务于旧 answer 执行图的代码与测试，并保持统一循环行为不变。
- 明确历史 Run 的执行恢复白名单，旧快照只读、不转入新循环。
- 保留公开 API、历史投影、数据库字段、Workspace/权限与人在环边界。

**Non-Goals:**

- 不调整 `dialogue_loop` 的模型、提示词、预算、工具或相关性规则。
- 不清理数据库历史记录、迁移、旧响应字段或移动端代码。
- 不修复回答内容质量问题，不进行阿里云部署。

## Decisions

### 1. 取消控制独立为无编排职责的公共模块

新建 `services.knowledge_agent.run_control`，只提供 `RunCancelled` 和基于独立短会话读取最新 Run 状态的取消检查。所有现行调用方改为直接依赖该模块。

选择独立模块而不是把能力放进 Worker 或 `runs.py`，因为取消检查同时被 Worker、统一循环适配器、operation Run 和只读搜索复用；它不应拥有任何 answer 规划职责。异常类型和触发条件保持不变。

### 2. 按可达性与职责删除旧执行器，保留兼容投影

删除 `runner`、旧 investigation 执行器、复合回答执行、覆盖补查、共享执行图以及只被这些路径调用的 Agent/服务模块。对混合模块先迁移现行调用点，只删除旧编排部分；`composite_answer_projection`、Run/Conversation schema、调查详情读取、模型字段和 Alembic 历史迁移继续保留。

dialogue-loop 的动态插桩和子进程预检清单只保留当前循环实际需要的模块，避免已删除模块成为隐式导入依赖。配置中的旧键本次不删除，以免形成部署配置合同的额外变更；它们变为无执行消费者的兼容键，后续可独立清理。

### 3. answer Run 恢复采用显式白名单

Worker 根据 `run_kind` 和 `current_step` 判断恢复：

- Candidate 与 Entry Revision 保持当前幂等重试规则。
- answer Run 在 `claim` 或 `recovered` 阶段可重新入队，因为尚未进入编排。
- `dialogue_loop` 仅在现有持久化状态检查允许时重新入队；处于内存处理中或状态损坏时失败。
- 旧步骤名、空步骤或未知步骤明确标为失败，并记录“旧执行快照不可恢复”，不得调用统一循环。

选择失败收尾而不是转换旧快照，是因为两套执行器的检查点、预算和事实句柄并不等价；自动转换会重复工具调用、绕过旧状态判断或造成伪恢复。历史 API 仍可读取失败 Run 及其既有审计数据。

### 4. 测试按合同迁移，不保留旧执行器夹具

只验证旧 runner/investigation/composite/coverage/shared graph 内部执行的测试随实现删除。Web API、Candidate、Entry Revision、Workspace、权限、取消、幂等和恢复测试继续保留，并把旧 runner monkeypatch 改为统一 `production_adapter`/dialogue-loop 的确定性边界。这样测试失败反映当前链路，而不是已失效的注入点。

## Risks / Trade-offs

- [历史 processing Run 无法继续完成] → 旧步骤显式失败并保留可读审计；不以不等价的新循环接管。
- [误删现行底层能力] → 删除前后用静态导入、动态导入、脚本入口和相关测试四类证据核对；兼容投影与数据库模型单独保留。
- [测试迁移掩盖行为变化] → 只替换确定性执行夹具，不删除现行合同断言；与同环境基线逐项比较。
- [保留旧配置键形成技术债] → 本 change 不改变部署配置合同，在验证记录中登记实际残留依赖。

## Migration Plan

1. 先加入公共取消模块并迁移现行调用方，以测试证明行为等价。
2. 加入历史恢复白名单与回归测试。
3. 删除无现行调用方的旧编排模块、动态导入与专属测试，执行静态扫描和受影响测试。
4. 部署时不需要数据库迁移；回滚使用本 change 的本地提交逆序恢复代码。已被明确失败收尾的旧 processing Run 不自动恢复为 processing。

## Open Questions

无。旧执行器不作为回滚入口、历史数据只读保留均已由本 change 范围确定。
