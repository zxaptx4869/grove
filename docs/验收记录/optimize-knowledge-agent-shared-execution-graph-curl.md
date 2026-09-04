# Knowledge Agent 共享执行图 API curl 验收记录

来源 change：`optimize-knowledge-agent-shared-execution-graph`（任务 6.3）

验证日期：2026-09-04

## 环境与边界

后端使用本地开发 SQLite，迁移到当前 head，监听 `127.0.0.1:8000`。本机没有配置
文本模型密钥，因此真实 API 流程用于验证路由、认证、提交、Worker、历史、取消和
可观测性；共享执行图的串行等价、复用收益、节点失败、取消与恢复由固定测试夹具验证。
记录只保留脱敏结果，不保存 Cookie、内部查询、Entry/Source 全文或图指纹。

启动命令：

```bash
cd backend
.venv/bin/alembic upgrade head
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

验收完成后已正常停止服务。

## 路由、认证与真实 Worker

无认证时，Conversation、消息提交、Run、历史和可观测端点均返回 401，而不是 404；
`GET /healthz` 返回 200。

使用本地临时账号建立 Cookie 会话后的结果：

| 请求 | 结果 |
|---|---|
| `POST /api/auth/register` | 201 |
| `POST /api/knowledge-agent/conversations` | 201，创建 Workspace 范围对话 |
| `POST /conversations/{id}/messages` | 201，创建 waiting Run |
| `GET /runs/{id}` | 200，Worker 已推进至 completed |
| `GET /conversations` | 200 |
| `GET /conversations/{id}/messages` | 200 |
| `GET /runs/{id}/observability` | 200 |
| `POST /runs/{id}/cancel` | 200；终态 Run 幂等保持终态 |

由于未配置文本模型，真实 Run 明确返回 `context_degraded=true`，fallback 摘要和可观测
记录均包含 `provider=offline`、`model=null`、`is_fallback=true` 和“未配置文本模型密钥”；
没有把离线结果伪装为模型成功。

## 串行/共享等价与实际调用次数

固定同一份已规范化计划分别执行既有串行路径与共享图路径，评估夹具结果为 18 项全部
通过。重复 retrieval 的实际底层调用计数如下：

| 底层调用 | 串行路径 | 共享图路径 |
|---|---:|---:|
| 语义检索 | 2 | 1 |
| Entry 内容读取 | 2 | 1 |
| Evidence 核验 | 2 | 1 |

两条路径的 request 状态、完整性、Entry、Evidence、count/group/list 工具事实、逐项覆盖、
answer basis 和最终状态保持等价。同一集合上的 count/group/list 仍分别执行所需的只读聚合，
不会从展示列表数量反推统计值。

## 节点失败、预算、取消与恢复摘要

- 上游检索失败只发生一次实际调用，后继节点由调度器传播失败，所有失败均有 server
  audit，不会整体回退串行重放；
- `completed/empty/limited/partial/failed` 五类已提交终态恢复时均复用，只运行尚未提交的
  节点；完整 state 再次执行产生 0 次节点调用和 0 次重复检查点；
- 节点返回超过预分配额度时转为显式 failed，并留下预算错误审计；损坏的上游指纹或超过
  冻结总预算的 state 被拒绝；
- 并行波次收到取消后，协调器不接纳迟到结果，不写入检查点、Evidence、成功审计或正常
  回答；
- Run、Workspace、项目均进入范围指纹，不存在跨范围或跨 Run 复用；配置或开关变化后，
  已持久化 Run 仍使用自身冻结图恢复。

对应命令：

```bash
cd backend
.venv/bin/pytest -q tests/test_knowledge_agent_shared_execution_graph_eval.py
.venv/bin/pytest -q tests/test_knowledge_agent_worker.py \
  tests/test_knowledge_agent_shared_execution_graph.py \
  -k 'recovery or parallel or budget or cancel or corrupt or idempotent'
```

## 公开协议

Run 与消息页只返回既有有界复合计划/覆盖投影，不返回共享图、state、内部 execution、节点
fingerprint、内部查询、Entry/Source 全文、授权参数或隐藏推理。图字段为空的旧 Run 仍能从
Run 与消息历史端点正常读取；原生端无需新增 graph 类型或 UI。

## 结论

真实服务端路由和鉴权符合预期，未配置模型时降级透明可见。固定评估证明共享图在保持既有
回答语义和安全边界的同时消除了等价 retrieval 的重复底层调用；节点失败、预算、取消、
恢复和重复提交均有明确且可验证的行为。
