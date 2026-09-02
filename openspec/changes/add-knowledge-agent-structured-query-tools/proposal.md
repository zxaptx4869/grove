## Why

Knowledge Agent 现有综合回答和结构化 Entry 查找都建立在有限相关性召回上，无法可靠回答精确计数、结构化筛选、排序、分组以及“统计后列出对象”等组合问题。阶段 A 已让 Agent 能按依据开放讨论，现在需要先建立受 Workspace 范围约束、由服务端确定性执行的结构化查询工具，避免继续为单条问法扩张路由规则或让模型根据 top-k 结果猜测精确结论。

## What Changes

- 定义版本化、受限的 `EntrySetSpec`，表达当前 Workspace 或项目范围内正式 Entry 的允许筛选、排序、分页、分组和聚合条件；模型只生成候选计划，服务端负责校验、规范化和执行。
- 增加 `query_entries` 与 `aggregate_entries`，第一版支持按项目范围、知识类型、内容性质、更新时间和受控文本条件筛选，支持稳定排序、精确计数及受限分组，并能在一次计划中共享同一筛选集合完成“统计 + 列表”。
- 建立统一只读工具执行入口与版本化结构化结果账本，记录规范化参数、范围、状态、精确性、数量、耗时和错误摘要，但不复制无限正文或接受模型传入授权范围。
- 将现有 `entries` 执行图扩展为一次结构化查询计划：能够返回筛选说明、聚合结果和可选 Entry 快照；无法证明完整性时明确返回 `limited` 或 `unknown`，不得把相关结果包装成精确全集。
- 在原生 Entry 结果中展示结构化筛选摘要、统计/分组结果、排序方式、完整性和可选 Entry 卡，继续支持历史恢复、分页、当前对象复验和结果形态纠正。
- 通过特性开关和兼容字段渐进上线；旧客户端、旧 Run 与既有语义查找继续按当前主规格恢复，不迁移或猜测历史查询计划。
- 增加精确查询、组合查询、越权参数、非法计划、预算限制、恢复、取消、降级和 SQLite/MySQL 8 一致性的代表性测试。

### Non-Goals

- 不在本 change 中实现基于中间工具结果继续选择下一工具的多轮自主循环；quick 与 investigate 统一复用工具集留给阶段 B 的第二个 change。
- 不移除现有固定检索 Workflow，也不改变综合回答、开放讨论和回答依据的既有执行边界。
- 不支持目录作为用户可选查询范围，不允许模型或客户端指定 Workspace、任意项目或任意 Entry 标识绕过 Run 固化范围。
- 不支持任意 SQL、自由表达式、全文导出、无限结果、复杂分析函数或跨 Workspace 聚合。
- 不创建、补充、修订、移动、合并或删除 Entry，不进入 `prepare_operation`，不改变 Candidate Draft 与 Entry Revision 流程。
- 不引入外部搜索、Discovery、后台无限任务或基于行为数据自动调整规划策略。

## Capabilities

### New Capabilities

- `knowledge-agent-structured-query-tools`: 定义受限 `EntrySetSpec`、确定性 `query_entries`/`aggregate_entries`、共享集合组合执行、精确性边界和结构化工具结果账本。

### Modified Capabilities

- `knowledge-agent-read-tools`: 既有语义搜索与 Entry/Evidence 读取接入统一只读工具执行约束和审计协议，但继续保持可信范围与 Evidence 边界。
- `knowledge-agent-structured-entry-search`: `entries` 结果从有限相关性列表扩展为一次结构化查询计划的筛选、统计、分组和可选 Entry 快照，并保持完整性诚实表达。
- `knowledge-agent-run`: Run 固化版本化查询计划并原子提交结构化工具结果；取消、租约恢复、幂等和可观测性覆盖确定性查询执行。
- `native-knowledge-agent-entry-results`: 原生端展示筛选摘要、统计/分组、排序、完整性和可选 Entry 列表，并兼容没有新字段的历史结果。

## Impact

- 后端将新增结构化查询领域模型、计划校验器、SQLAlchemy 查询/聚合服务、统一执行入口、结果账本与对应迁移，并扩展 Knowledge Agent Run、API schema 和 Worker 的 `entries` 分支。
- 数据库需要同时兼容 SQLite 与 MySQL 8；所有筛选、排序、分组和计数必须使用两者语义一致的受控字段与确定性 tie-breaker。
- 原生 App 将扩展 Entry 结果协议、适配器和结果组件，但继续复用 Conversation、Run 轮询、Entry 卡、详情 Sheet 与结果形态纠正能力。
- AI 调用继续复用现有 provider/model/fallback 审计；计划失败必须显式降级到既有有限语义查找或返回可解释失败，不得静默伪装为精确查询成功。
- 正式 Entry、Source、Candidate 与目录数据模型不因查询被写入或修改；Workspace 隔离、可追溯、人在环上和禁止静默降级的产品铁律保持不变。
