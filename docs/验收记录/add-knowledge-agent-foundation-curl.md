# 知识 Agent API curl 验证记录

来源 change：`add-knowledge-agent-foundation`（任务 5.4）
验证日期：2026-08-28
环境：本地开发后端，SQLite（`backend/grove.db`），端口 8011。

## 启动命令

```bash
cd backend
.venv/bin/alembic upgrade head   # 迁移到 a0b1c2d3e4f5
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8011
```

## 验证结果（HTTP 状态码）

| 步骤 | 请求 | 预期 | 实际 |
|---|---|---|---|
| 未登录访问 | `GET /api/knowledge-agent/conversations` | 401 | 401 |
| 注册用户 A | `POST /api/auth/register` | 201 | 201 |
| 创建对话 | `POST /api/knowledge-agent/conversations` | 201 | 201 |
| 列出对话 | `GET /api/knowledge-agent/conversations` | 200 | 200 |
| 提交问题 | `POST /api/knowledge-agent/conversations/{id}/messages` | 201（waiting Run） | 201 |
| 轮询 Run | `GET /api/knowledge-agent/runs/{id}` | 200（终态+回答） | 200（completed，回答 insufficient） |
| 读取消息 | `GET /api/knowledge-agent/conversations/{id}/messages` | 200 | 200 |
| 可观测性 | `GET /api/knowledge-agent/runs/{id}/observability` | 200 | 200（含 search 工具调用） |
| 活动 Run 时再提问 | `POST .../messages`（新 client_message_id） | 409 | 409 |
| 切换范围 | `PATCH .../conversations/{id}/scope` | 200 | 200 |
| 不存在 Run | `GET /api/knowledge-agent/runs/999999` | 404 | 404 |
| 跨 Workspace 访问对话 | 用户 B `GET .../conversations/{A 的 id}` | 404 | 404 |

所有端点均为业务状态码（401/200/201/404/409），未出现 404 路由缺失。

## 可复现命令

```bash
cd /tmp
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8011/api/knowledge-agent/conversations
curl -s -c cookies.txt -H 'Content-Type: application/json' \
  -d '{"username":"curl_agent_a","password":"password123"}' \
  http://127.0.0.1:8011/api/auth/register
curl -s -b cookies.txt -H 'Content-Type: application/json' \
  -d '{"scope_type":"workspace"}' \
  http://127.0.0.1:8011/api/knowledge-agent/conversations
curl -s -b cookies.txt -H 'Content-Type: application/json' \
  -d '{"client_message_id":"curl-msg-1","message":"闭水试验通常持续多久？"}' \
  http://127.0.0.1:8011/api/knowledge-agent/conversations/{id}/messages
curl -s -b cookies.txt http://127.0.0.1:8011/api/knowledge-agent/runs/{run_id}
curl -s -b cookies.txt http://127.0.0.1:8011/api/knowledge-agent/runs/{run_id}/observability
```

## 备注

- 提交第二个问题的 409 需要与第一个问题在同一处理窗口内连续提交（进程内 Worker 每 0.5s 轮询）。
- 验证期间产生的测试数据保留在开发库 `backend/grove.db`，可在人工验收后清理。

## SQLite 手动走查覆盖（6.2）

SQLite（开发库与测试库）已通过自动化测试覆盖以下场景，测试文件：
`test_knowledge_agent_conversations.py`、`test_knowledge_agent_tools.py`、
`test_knowledge_agent_evidence.py`、`test_knowledge_agent_runner.py`、
`test_knowledge_agent_worker.py`、`test_knowledge_agent_api.py`。

- Workspace 问答：跨项目搜索、项目归属与目录定位；
- 项目问答：只读本项目正式 Entry；
- 跨 Workspace 隔离：对话、Run、消息一律 404；
- 真实原文引用：Attachment 文本/OCR 归一化定位后保存精确子串；
- 幂等：同一 `client_message_id` 返回首次消息与 Run；
- 取消：waiting/processing 取消不写回答、释放活动槽；
- 重启恢复：超过租约的 processing Run 重新入队一次，超过上限失败；
- 降级：embedding/重排/回答各阶段分别记录 provider/model/fallback/error/耗时，
  回答模型不可用时 Run 为 `partial`、回答状态为 `failed`。

## MySQL 8 真实验证（6.2）

使用一次性临时 MySQL 8.0.45 实例（独立端口 33062、全新数据目录，验证后已删除）：

```bash
mysqld --no-defaults --initialize-insecure --datadir=<tmp> --user=$(whoami)
mysqld --no-defaults --datadir=<tmp> --port=33062 --socket=<tmp>/mysql.sock --bind-address=127.0.0.1
DATABASE_URL="mysql+asyncmy://root@127.0.0.1:33062/grove_ka_test" .venv/bin/alembic upgrade head
```

结果：

- 完整迁移链（含 `a0b1c2d3e4f5` 知识 Agent 表）在 MySQL 8 执行成功；
- 同一对话插入第二个 `active_slot='active'` Run → `ERROR 1062 Duplicate entry '1-active' for key 'uq_knowledge_run_active_slot'`；
- 终态 `active_slot=NULL` 可并存多行（MySQL 唯一索引允许多个 NULL），与 SQLite 语义一致；
- 同一对话重复 `client_message_id` → `ERROR 1062 Duplicate entry '1-client-1' for key 'uq_knowledge_message_client_id'`。
