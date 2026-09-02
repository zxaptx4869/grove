# 知识 Agent 开放讨论 API curl 验收记录

来源 change：`add-knowledge-agent-open-discussion`（任务 8.1）
验证日期：2026-09-02
环境：本地开发后端，独立验收库 `backend/grove_accept_open.db`（迁移到
`c7d8e9f0a1b2`），端口 8022，进程内 Worker 开启，
`KNOWLEDGE_AGENT_OPEN_DISCUSSION_ENABLED=true`；未配置模型密钥，因此
规划/路由/回答模型全部走确定性或离线降级——正好用于验证「依据模式固化、
开放开关开启、降级可见、调查落库、basis 快照与幂等复用」路径。

## 启动命令

```bash
cd backend
DATABASE_URL="sqlite+aiosqlite:///./grove_accept_open.db" .venv/bin/alembic upgrade head
DATABASE_URL="sqlite+aiosqlite:///./grove_accept_open.db" \
  KNOWLEDGE_AGENT_OPEN_DISCUSSION_ENABLED=true \
  KNOWLEDGE_AGENT_WORKER_ENABLED=true \
  .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8022
```

## curl 走查命令与响应摘要

走查脚本：未登录探活 → 注册新用户 → 建项目/节点/来源 → 处理并归档
候选为正式 Entry → 创建项目范围对话 → 依次提交 knowledge_only /
auto / investigate / 同 `client_message_id` 篡改依据重试 → 读取消息页、
Run、可观测与调查接口。

| 步骤 | 命令 | 结果 |
|---|---|---|
| 未登录访问 | `GET /api/knowledge-agent/conversations` | 401 |
| 注册用户 | `POST /api/auth/register` | 201，用户 `accept_open_20260902` |
| 建项目/节点/来源 | `POST /projects`、`/projects/1/nodes`、`/api/sources` | 201/201/201 |
| 处理并归档 Entry | `POST /sources/1/process` + `POST /candidates/1/archive` | 200/200；Entry 含真实 Evidence |
| 创建对话 | `POST /api/knowledge-agent/conversations` | 201（项目范围） |
| knowledge_only + quick | `POST .../messages`：`basis_mode=knowledge_only`、`answer_mode=quick` | 201；Run 1 终态 `partial`，回答模型离线 → `answer.status=failed`（可见降级）；`answer_basis`：grove 0、模型知识 false、外部 not_used；observability 汇总 embedding/rerank/answer 三级 fallback |
| auto + quick（个人化问法） | `basis_mode=auto`、`answer_mode=quick` | 201；Run 2 `completed`；规划器离线回退 Grove-only，搜索空 → `answer.status=insufficient`（无 Citation 不再自动等于失败，但也未开放模型知识）；`answer_basis` 全空 |
| auto + investigate | `basis_mode=auto`、`answer_mode=investigate` | 201；Run 3 `partial`；真实创建 Investigation：`rounds_completed=1`、`queries_executed=0`、`stop_reason=insufficient`；调查接口 200 |
| 同 `client_message_id` 篡改模式重试 | 以 `basis_mode=auto`、`answer_mode=investigate` 重发 `open-ko-1` | 200；返回首次 Run 1（`request_basis_mode=knowledge_only`、`request_answer_mode=quick`），依据限制不被重试参数放宽 |
| 消息页 | `GET /conversations/1/messages?limit=30` | 200；6 条消息、3 个去重 Run；Run/消息均含 `request_basis_mode` 与 `answer_basis` |
| Run 可观测 | `GET /runs/1/observability` | 200；显式 knowledge_only 无 `basis_route` 模型调用；`context_decision` 服务端、embedding/rerank/answer 降级可见；工具留痕 search/read 正常 |

## 响应关键字段快照（节选）

- 显式 knowledge_only 固化：提交响应 `request_basis_mode: "knowledge_only"`；
  重试（携带 auto/investigate）返回 `request_basis_mode: "knowledge_only"`、
  `request_answer_mode: "quick"`，服务端未更新原 Run。
- Run 终态 basis：Run 1 `answer_basis` =
  `{"schema_version":"v1","grove":{"used":false,...},"user_statements":{"message_ids":[]},
   "model_knowledge":{"used":false},"external_material":{"status":"not_used"}}`
  —— 回答模型离线时没有把“AI 通用知识”误标为已使用。
- 降级可见：Run 1 `fallback_summary.has_fallback=true`，stages 含
  `embedding`（未配置豆包密钥）、`rerank`/`answer`（未配置文本模型密钥）；
  Run 2 在规划器离线回退后没有伪造 `basis_route` 模型调用。
- 调查真实性：Run 3 `investigation_summary` 保留真实停止原因
  `insufficient`，`GET /runs/3/investigation` 返回 200 与逐轮详情。
- 消息页：`request_basis_mode`/`answer_basis` 字段在消息与 Run 上均返回；
  旧客户端缺省按 `knowledge_only` 兼容语义不受影响。

## 依赖真实模型的路径说明

model-first 正常开放回答、hybrid 多类依据与 knowledge_first 带引用完成
在本环境无模型密钥时只能以「规划器离线回退 + 回答模型失败」的可见降级
形态触发；真实完成路径由自动化评估/硬门禁测试覆盖：

- `tests/test_knowledge_agent_open_discussion.py`：模型优先、知识优先、
  混合、仅我的知识、冲突、时效/外部缺口与同义表达评估 + 安全硬门禁；
- `tests/test_knowledge_agent_runner.py`：model-first 跳过 Grove 完成、
  依据审计、空搜索/不可用/失败路径、恢复复用规划；
- `tests/test_knowledge_agent_investigation_runner.py`：显式 investigate
  强制真实 Grove、自动 model-first 不伪造调查、无证据一般回答；
- `tests/test_knowledge_agent_worker.py`：取消不提交迟到回答、恢复不漂移。
