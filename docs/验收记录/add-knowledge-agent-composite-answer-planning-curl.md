# 知识 Agent 复合回答规划 API curl 验收记录

来源 change：`add-knowledge-agent-composite-answer-planning`（任务 7.1）

验证日期：2026-09-03

## 环境与边界

使用隔离临时 SQLite 库 `/private/tmp/grove_composite_accept_20260903.db`，迁移到
`fa1b2c3d4e5f`，后端监听 `127.0.0.1:8032`。启用开放讨论、B1 结构化查询与复合回答
开关；除真实 fallback 验证外关闭 Knowledge Agent Worker。

当前机器未给这个隔离账号配置文本模型。因此验收分为三类：

- 真实 API 流程：移动端注册、Conversation、消息提交、幂等重试、Run/历史查询和
  waiting Run 取消；
- 公开响应契约走查：在同一隔离库写入经现有 Pydantic/API schema 验证的终态快照，
  用 curl 核对混合回答、精确统计、limited、knowledge-only、非法计划与恢复投影；
- 真实离线执行：启用 Worker 后提交一条新问题，验证未配置模型时的显式 fallback。

契约快照不声称来自现场模型生成。规划、执行、只读性、恢复和非法输入的真实行为由
`test_knowledge_agent_composite_answer*.py`、`test_knowledge_agent_worker.py` 及后端
全量测试覆盖。验收完成后已停止服务；临时数据库、Token 和临时 SQL 均未写入仓库。

## 启动命令

```bash
cd backend
DATABASE_URL="sqlite+aiosqlite:////private/tmp/grove_composite_accept_20260903.db" \
  .venv/bin/alembic upgrade head

DATABASE_URL="sqlite+aiosqlite:////private/tmp/grove_composite_accept_20260903.db" \
  PROCESSING_WORKER_ENABLED=false CONTEXT_WORKER_ENABLED=false \
  DIRECTORY_DRAFT_WORKER_ENABLED=false EMBEDDING_WORKER_ENABLED=false \
  KNOWLEDGE_AGENT_WORKER_ENABLED=false \
  KNOWLEDGE_AGENT_OPEN_DISCUSSION_ENABLED=true \
  KNOWLEDGE_AGENT_STRUCTURED_QUERY_ENABLED=true \
  KNOWLEDGE_AGENT_COMPOSITE_ANSWER_ENABLED=true \
  .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8032
```

真实 fallback 验证只把 `KNOWLEDGE_AGENT_WORKER_ENABLED` 改为 `true` 后重启同一服务。
Bearer Token 由 `/api/auth/mobile/register` 返回；记录中以 `$AUTH_TOKEN` 替代原值。

## 路由与认证状态

以下无认证请求均返回 401，不是 404：

```bash
curl http://127.0.0.1:8032/api/knowledge-agent/conversations
curl -X POST http://127.0.0.1:8032/api/knowledge-agent/conversations
curl -X POST http://127.0.0.1:8032/api/knowledge-agent/conversations/1/messages
curl http://127.0.0.1:8032/api/knowledge-agent/runs/1
curl http://127.0.0.1:8032/api/knowledge-agent/conversations/1/messages
curl -X POST http://127.0.0.1:8032/api/knowledge-agent/runs/1/cancel
```

带有效 Bearer 后的真实流程：

| 请求 | 结果 |
|---|---|
| `POST /api/auth/mobile/register` | 201，返回非空 Token |
| `POST /api/knowledge-agent/conversations` | 201，创建 Workspace 范围对话 |
| `POST /conversations/2/messages` | 201，创建 waiting Run 1 |
| 相同 `client_message_id` 再次提交 | 200，幂等返回原 Run |
| `GET /runs/1` | 200 |
| `GET /conversations/2/messages` | 200 |
| `POST /runs/1/cancel` | 200，Run 为 cancelled |

真实取消响应的关键字段为：

```json
{
  "id": 1,
  "status": "cancelled",
  "cancel_requested": true,
  "composite_answer_plan": null,
  "composite_answer_coverage": null
}
```

## 复合回答公开响应

下列 Run 均通过 `GET /api/knowledge-agent/runs/{id}` 取得 200，并通过消息历史端点读取到
同一份有界计划和覆盖投影。响应不包含检索词、Entry/Source 全文、内部 Evidence/result
句柄、prompt 或授权参数。

### 一般解释与 Grove 义务

Run 2 将原始混合问题保留为两个回答义务：

- “解释甲醛是什么”：`model_allowed`，状态 `answered`，依据为
  `model_knowledge`；
- “结合 Grove 说明来源和环保等级”：`grove_required`，状态
  `insufficient`，没有借用第一项的模型知识伪装完成。

整体 Run/answer 均为 `partial`，回答先给出简明概念解释，再明确当前范围缺少可核验的
Grove 证据。

### 解释与精确统计

Run 3 的计划包含解释义务和结构化统计义务，`input_kinds=[structured]`。统计 point 使用
服务端工具事实“符合条件的知识条目共 12 条”，覆盖依据为 `structured_result`；整体
Run/answer 均为 `completed`。精确数值来自 complete 的纯结构化集合，不从展示列表反推。

### limited 统计

Run 4 的语义集合返回“本次有限候选中有 5 条相关知识；不代表当前范围内的精确总数”。
Run/answer 与对应义务均为 `partial`，note 为“仅覆盖语义候选集合”，没有将 top-k 数量
包装成全集精确计数。

### knowledge-only

Run 5 的唯一义务被收紧为 `grove_only`。当前范围没有合法 Evidence 时回答状态为
`insufficient`，`basis_kinds=[]`，实际依据中的 `model_knowledge.used=false`，没有使用
模型通用知识补齐。

### 非法计划

Run 6 的越权对象 id 候选被服务端拒绝，公开响应不返回非法计划或覆盖快照，并进入既有
安全回答路径。fallback 摘要明确返回：

```json
{
  "purpose": "composite_answer_plan",
  "is_fallback": true,
  "provider": "llm",
  "model": "accept-model",
  "error": "计划含越权对象 id，服务端拒绝"
}
```

### 恢复

Run 7 返回合法计划、`answered` 覆盖和完成回答。可观测端点返回 200，只含一次
`composite_answer_plan`、一次 `answer`，以及一个 `aggregate_entries` 完成检查点；参数
摘要含 `fingerprint=stable-recovery-fingerprint`，结果摘要标记 `reused=true`。同指纹不
再次规划或执行、仅重放缺失只读步骤的行为由 Worker 恢复测试验证。

## 真实离线 fallback

启用 Worker 后提交 Run 8，最终为 `completed`，answer 为 `insufficient`，没有复合计划。
Run 与可观测接口同时返回：

```json
{
  "purpose": "composite_answer_plan",
  "provider": "offline",
  "model": null,
  "is_fallback": true,
  "error": "未配置文本模型密钥"
}
```

后续 `basis_route` 也以同样字段明确记录离线降级，未静默伪装成真实模型成功。

## 结论

Conversation、提交、Run 查询、消息历史和取消端点均满足预期 401/200/201，不存在 404。
公开协议能够表达混合义务、逐项覆盖、精确/limited 统计、knowledge-only、非法计划、
取消、恢复和真实 fallback，同时保持内部查询、句柄、prompt 与范围授权信息不外泄。
