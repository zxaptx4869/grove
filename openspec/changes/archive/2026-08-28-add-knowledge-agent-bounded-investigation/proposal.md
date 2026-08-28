## Why

知识 Agent 已能理解连续追问并基于显式工作集完成一次检索，但复杂问题仍只有“一次查询、一次召回、一次回答”：首轮关键词不理想、问题包含多个方面或证据相互矛盾时，Agent 不会根据已看到的结果继续补查。现在需要在不联网、不写知识和不开放无限工具循环的前提下，让它具备“观察证据 → 发现缺口 → 再查一轮 → 有依据地停止”的有限自主调查能力。

## What Changes

- 消息提交新增回答模式 `auto`、`quick`、`investigate`：`quick` 沿用现有单轮链路，`investigate` 强制有界调查，`auto` 由结构化路由判断；路由失败显式降级为 `quick`。
- 新增持久化 Investigation 与 Round：保存调查目标、实际模式、轮次上限、当前轮次、计划查询、覆盖/缺口摘要、停止原因和恢复位置；默认最多三轮，不允许后台无限运行。
- 新增结构化调查控制器：每轮只能根据当前问题、工作集与证据账本提出有限数量的新检索查询，或选择回答/知识不足；应用层负责工具执行、范围校验、去重、预算和强制停止。
- 新增 Run 内证据账本：按轮次聚合已发现 Entry、当前 Run Evidence、覆盖主题、冲突线索与不可用对象；历史助手回答和历史 Run Evidence 仍不能成为事实。
- 每轮自动执行受控的“搜索正式知识 → 读取 Entry → 读取/核验 Source Evidence”，新结果回填控制器；重复查询、无新增知识、达到轮次/查询/Entry/Evidence 预算时确定性停止。
- 最终回答附调查摘要，包括实际模式、完成轮数、查询数、停止原因和未解决缺口；事实结论仍只能引用本 Run 核验 Evidence，未覆盖部分必须明确标记。
- 崩溃恢复复用已完成轮次和证据账本，从下一未完成轮次继续；取消在每个模型调用和工具批次边界检查，已持久化轮次保留审计但不产生正常回答或工作集更新。
- 硬化连续追问历史选择：排除当前 Run 的用户消息和空助手占位消息，避免占位挤掉有效历史；修复跨会话取消测试暴露的 aiosqlite 连接回收警告。
- 更新 Agent 与 AI 阅读权威专题，明确 quick 与深度调查的产品差异、预算边界和停止语义。

### Non-Goals

- 不联网搜索、不抓取网页、不创建新 Source，也不接入 Discovery Agent；调查仅使用当前 Workspace/项目内正式知识。
- 不提供知识新增、修改、移动、删除、合并或保存回答工具；最终回答不是正式 Entry。
- 不实现 Web 或原生 App UI、流式输出、推送、离线运行或后台定时研究。
- 不让模型直接控制 Workspace/项目、数据库事务、任意工具名、工具次数或停止上限。
- 不引入通用多 Agent 框架、外部任务队列、向量数据库或新的模型供应商依赖。
- 不实现跨对话长期记忆、用户画像、自动学习提示词或自动调整预算。

## Capabilities

### New Capabilities

- `knowledge-agent-investigation`: quick/auto/investigate 模式、结构化调查计划、最多三轮的观察—补查循环、停止规则、取消和恢复。
- `knowledge-agent-investigation-ledger`: Run 内跨轮次的查询、Entry、Evidence、覆盖、缺口与冲突账本，以及去重和审计契约。

### Modified Capabilities

- `knowledge-agent-conversation`: 消息提交增加回答模式并保持幂等，消息与 Run 返回实际模式和调查摘要。
- `knowledge-agent-run`: 固定单轮执行图扩展为 quick 单轮或有预算调查分支，持久化轮次进度、停止原因与逐轮可观测性。
- `knowledge-agent-read-tools`: 允许调查控制器提出文本查询，工具按轮次执行并共享本 Run 已发现集合，同时实施全局预算、去重与可信范围。
- `reader-qa`: 深度回答可综合多轮证据，并返回覆盖、未解决缺口与停止原因；所有事实引用仍来自当前 Run Evidence。

## Impact

- 后端新增 Investigation、Round、Query/Observation 或等价账本模型及 Alembic 迁移，并扩展 Run 的回答模式和调查摘要字段。
- 新增调查模式路由/控制器 Agent、调查编排服务、预算与恢复逻辑；复用现有上下文决策、工作集、混合检索、Evidence、Worker 与 `AIProvider`。
- 扩展知识 Agent schemas、消息提交/API 响应、工具/模型调用的轮次归属与手动走查记录。
- 调整有限历史选择和相关并发测试资源管理，修复验收发现的小缺口。
- 更新 `docs/产品蓝图/Agent架构与AI边界.md` 与 `docs/产品蓝图/目录与知识空间.md`。
- 本 change 只通过 API、自动测试和 SQLite/MySQL 走查验收；客户端以后可据调查摘要展示“快速回答 / 深度查找”和进度。
