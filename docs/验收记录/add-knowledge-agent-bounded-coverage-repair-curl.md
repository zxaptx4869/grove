# Knowledge Agent 一次有界覆盖补查 API curl 验收记录

来源 change：`add-knowledge-agent-bounded-coverage-repair`（任务 6.2）

验证日期：2026-09-04

## 环境与边界

使用独立临时 SQLite 数据库完成全量迁移 `upgrade → downgrade -1 → upgrade`，再以
`KNOWLEDGE_AGENT_COMPOSITE_ANSWER_ENABLED=true`、
`KNOWLEDGE_AGENT_COVERAGE_REPAIR_ENABLED=true` 启动本地后端。服务监听
`127.0.0.1:8014`，验收结束后已正常停止。

本机没有配置文本模型密钥，因此真实 API 流程用于验证路由、认证、提交、Worker、历史、
取消、公开协议与可观测性；补查 planner 候选、串行/共享图等价、Evidence 复用、失败保底、
预算、取消和恢复使用固定模型与只读工具夹具验证。记录不保存 Cookie、密码、内部查询、
Entry/Source 全文、图、范围指纹或隐藏推理。

## 迁移往返

- 新数据库从空版本升级到 `fc3d4e5f6a7b` 成功；
- `downgrade -1` 回到 `fb2c3d4e5f6a` 成功；
- 再次升级到 `fc3d4e5f6a7b` 成功；
- 旧行新增的五个补查快照字段均为 nullable，公开响应没有新增对应字段。

## 路由、认证与真实 Worker

未认证请求结果：

| 请求 | 状态 |
|---|---:|
| `GET /healthz` | 200 |
| `GET /api/knowledge-agent/conversations` | 401 |
| `GET /api/knowledge-agent/runs/{id}` | 401 |
| `GET /conversations/{id}/messages` | 401 |
| `GET /runs/{id}/observability` | 401 |
| `POST /runs/{id}/cancel` | 401 |

认证后的脱敏流程结果：

| 请求 | 结果 |
|---|---|
| `POST /api/auth/register` | 201 |
| `POST /api/knowledge-agent/conversations` | 201，Workspace 范围 |
| `POST /conversations/{id}/messages` | 201，创建 waiting Run |
| `GET /runs/{id}` | 200，Worker 推进至 completed |
| `GET /conversations/{id}/messages` | 200，用户/助手消息各一条 |
| `GET /runs/{id}/observability` | 200 |
| `POST /runs/{id}/cancel` | 200，终态 Run 幂等保持终态 |

真实 Run 固化为 quick/answer。由于没有文本模型密钥，复合计划阶段明确记录
`provider=offline`、`model=null`、`is_fallback=true`，最终为可见的 insufficient/fallback；
它没有伪造补查计划、完整 coverage 或模型成功。

## 有界补查自动化摘要

- 代表性“模型解释 + Grove Evidence + 结构化统计”夹具中，首次只让真实 Grove 来源缺口
  进入补查；补查后目标义务由 partial 改善为 answered，其他已回答义务不退化；
- 首次 coverage 全部 answered 时固化 `not_needed`，不调用 planner；不可修复的纯模型漏答
  和 `external_required` 不进入 Grove 补查；
- planner 最多尝试一次；未知字段、非准入目标、超预算、B1 非法结构、全重复以及混合重复
  候选均被服务端拒绝或确定性停止；
- 串行与共享图的请求状态、完整性、Entry 和 Evidence 语义一致；补查图节点不超过八个，
  图、state 与 execution 使用独立补查列；
- 同一 Run 的新查询命中相同 Entry/Source 时复用同一个 Evidence 句柄，Evidence 行总数仍为
  一；恢复后首次请求和补查请求的实际工具调用数均不增加；
- 工具预算不足时不发起调用并固化 limited；取消在 executing 检查点后、工具启动前停止；
  配置缩小和开关变化后仍使用 Run 冻结模式与预算；
- planner、执行或再综合失败时返回首次合法 answer/coverage/basis；coverage 退化候选被拒绝，
  `coverage_repair_synthesis` 进入 fallback 汇总；
- 项目范围统计只看到当前项目的一条 Entry，不包含同 Workspace 其他项目或其他 Workspace
  的 Entry；Entry、Source、Candidate、Draft/Extraction 和事实工作集前后计数不变。

## 公开协议

Run、Conversation 与消息页继续只投影既有 answer、points、Citation、coverage、gaps、basis、
fallback 和首次计划摘要。补查候选、查询、图、节点、状态、预算、范围与指纹不出现在公开
JSON；原生端无需新增补查协议或 UI。

## 结论

迁移、鉴权、提交、Worker、历史、取消和可观测端点符合预期；无模型时降级透明。固定评估
证明补查只发生一次、只执行新闭合只读请求，能减少真实缺口，同时在失败、取消、恢复、
预算和范围边界下保留首次合法结果且不产生知识写入副作用。
