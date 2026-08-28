# 知识 Agent 受限自主调查 API curl 验证记录

来源 change：`add-knowledge-agent-bounded-investigation`（任务 8.3 / 8.4）
验证日期：2026-08-28
环境：本地开发后端，SQLite（`backend/grove.db`，迁移到 `c4d5e6f7a8b9`），
端口 8013，进程内 Worker 开启；未配置模型密钥，因此路由/控制器/回答模型
全部走确定性/离线降级，正好用于验证「模式固化、降级可见、调查落库、
停止原因与逐轮详情」路径。

## 启动与迁移

```bash
cd backend
DATABASE_URL="sqlite+aiosqlite:///./grove.db" .venv/bin/alembic upgrade head
DATABASE_URL="sqlite+aiosqlite:///./grove.db" .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8013
```

## curl 走查结果（HTTP 状态码与关键字段）

走查脚本：注册新用户 → 建项目/节点/来源 → 处理并确认 Entry →
创建对话 → 依次提交 quick / auto / investigate / 幂等重试 / 取消 / 越权。

| 步骤 | 请求 | 结果 |
|---|---|---|
| 未登录访问 | `GET /api/knowledge-agent/runs/1` | 401 |
| 注册用户 | `POST /api/auth/register` | 201 |
| 建项目/节点/来源并确认 Entry | `/projects`、`/nodes`、`/sources`、`/process`、`/candidates/{id}/archive` | 201/201/201/200/200 |
| 创建对话 | `POST /api/knowledge-agent/conversations` | 201 |
| quick 单轮 | `POST .../messages`（`answer_mode=quick`） | 201；Run：`request=quick`、`actual=quick`、`partial`（回答模型离线 → `answer.status=failed`） |
| auto 路由 | `answer_mode=auto` | 201；Run：`request=auto`、`actual=quick`（路由离线降级）；observability 中 `answer_mode_route` 记录 `provider=offline`、`is_fallback=true`、`error=未配置文本模型密钥` |
| 强制 investigate | `answer_mode=investigate` | 201；Run：`actual=investigate`、`current_round=1`、`partial`；`investigation_summary`：`rounds_completed=1`、`queries_executed=0`、`stop_reason=insufficient` |
| 调查逐轮详情 | `GET /runs/{id}/investigation` | 200；`status=insufficient`、`stop_reason=insufficient`、1 个 round（`controller_action=insufficient`、`is_fallback=true`）、0 条查询、预算快照 `3/3/6/30/12` |
| 幂等重试 | 重发同 `client_message_id` 且 `answer_mode=quick` | 200；返回首次 Run（`request_answer_mode=investigate`、消息内容不变） |
| 取消 waiting Run | `POST /runs/{id}/cancel` | 200；`cancelled`、`active_slot=null`、无回答 |
| 跨用户隔离 | 另一用户读 `GET /runs/1` 与 `/runs/1/investigation` | 404/404 |
| 空消息拒绝 | 提交空白 message | 422（自动化测试覆盖；走查中因切换用户先命中 404 隔离） |

说明：`auto → investigate`、两轮补查、预算停止、多轮引用、冲突展示等
依赖真实模型的路径在本环境无法通过 curl 触发（路由/控制器离线时固定
quick/insufficient），由自动化测试以替身模型覆盖：

- `test_investigation_multi_round_discovery_and_citations`（两轮补查 + 多轮引用）；
- `test_investigation_budget_stops`（max_rounds / query / entry / evidence 预算）；
- `test_investigation_conflicts_kept_with_both_evidence`（冲突并列展示）；
- `test_investigation_working_set_only_cited_entries`（工作集过滤）；
- `test_api_investigation_run_completes_with_detail`（真实 API + 调查详情）。

## SQLite 迁移验证（8.2）

在临时 SQLite 库执行：

| 项目 | 结果 |
|---|---|
| 全新库 `upgrade head` | 成功到 `c4d5e6f7a8b9` |
| 轮次唯一约束 | `(investigation_id, round_number)` 重复插入被拒 |
| 查询指纹唯一约束 | `(investigation_id, normalized_query_hash)` 重复插入被拒 |
| 级联删除 | 启用 `PRAGMA foreign_keys=ON` 后删除 Run，调查/轮次/查询全清（MySQL 原生外键级联） |
| 旧库升级 | 先在 `b2c3d4e5f6a7` 建旧 Run，再 `upgrade head`：旧 Run 可读，`request_answer_mode/actual_answer_mode=None`、`current_round=0` |
| downgrade 再 upgrade | `downgrade b2c3d4e5f6a7` → `upgrade head` 均成功，调查表恢复 |

## MySQL 8 真实验证（8.4）

环境：一次性临时 MySQL 8.0.45 实例（`mysqld --no-defaults --initialize-insecure`，
独立数据目录与端口 33063，验证后已关闭并删除目录）。

```bash
DATABASE_URL="mysql+asyncmy://root@127.0.0.1:33063/grove_mysql_test?charset=utf8mb4" \
  .venv/bin/alembic upgrade head
```

### 验证结果

| 项目 | 结果 |
|---|---|
| 迁移链到 `c4d5e6f7a8b9` | 成功；三张调查表与 Run/调用/Evidence 新列均存在 |
| 旧 Run 兼容 | 不写回答模式字段的 Run 可读，模式为 NULL、`current_round=0` |
| 同调查轮次唯一约束 | 重复 `round_number=1` 报 IntegrityError（1062） |
| 同调查查询指纹唯一约束 | 重复 `normalized_query_hash` 报 IntegrityError（1062） |
| Run 删除级联 | 删除 Run 后调查/轮次/查询全部清理 |
| 运行中步骤可见 | 短会话提交 `current_step='round_search'`，新会话实时读到 |
| 跨事务取消 | 独立短会话提交 `cancel_requested=1` 后，`read_run_cancel_state` 读到 1 |
| 租约恢复 | `processing` + 过期 `claimed_at` 被重新入队（`recovered`）并可被 Worker 领取 |
| 终态一致性 | Run 终态、调查终态、助手消息同事务提交，提交后全部可见 |

## 自动验证

- `cd backend && .venv/bin/python -m pytest -W error`：全部通过，无 warning；
- `cd backend && .venv/bin/ruff check app tests`：全部通过。

注意：tasks.md 7.6 中列出的 `tests/test_ai_observability_api.py` 在仓库中
不存在；可观测性契约（模型/工具阶段、round/query 归属、正常 empty 不误报
fallback）由 `tests/test_knowledge_agent_api.py` 与本 change 新增的
`tests/test_knowledge_agent_investigation_api.py` 覆盖。

## 人工验收（用户委托代理执行）

验收日期：2026-08-28。用户将手动验收委托给代理执行：全新用户
`accept_investigation`、独立数据库 `backend/grove_accept.db`（迁移到
`c4d5e6f7a8b9`）、端口 8013，进程内 Worker 开启；未配置模型密钥。

| 场景 | 结果 |
|---|---|
| 未登录访问 Run | 401 |
| 注册 / 建项目节点来源 / 确认 Entry | 201/201/201/200/200 |
| quick 首问 | 201 → `request/actual=quick`、单轮、无调查摘要（`null`）；回答模型离线 → `partial` + `answer.status=failed`（符合设计） |
| auto | `actual=quick`（路由离线降级）；observability 记录 `answer_mode_route`：`provider=offline`、`is_fallback=true`、`error=未配置文本模型密钥` |
| 强制 investigate | `actual=investigate`、`current_round=1`、`partial`；`investigation_summary`：`rounds_completed=1`、`queries_executed=0`、`stop_reason=insufficient` |
| 逐轮调查详情 | `GET /runs/3/investigation` → 200；`status=insufficient`、预算快照 `3/3/6/30/12`、1 个 round（`controller_action=insufficient`、`is_fallback=true`）、0 条查询 |
| 幂等重试（同 `client_message_id` 改 quick） | 200；返回原 Run 3，`request_answer_mode=investigate`、消息内容不变 |
| 空消息 | 422 |
| 取消 waiting Run | `cancelled`、`active_slot=null`、无回答 |
| 跨用户隔离 | 另一用户读 Run 与调查详情均 404 |
| 调查相关自动化测试 | `test_knowledge_agent_investigation_{runner,recovery,api,ledger,agents}.py` 共 43 项全部通过（覆盖两轮补查、预算停止、多轮引用、冲突、恢复、取消与 API 契约） |

验收结论：回答模式固化与降级可见、调查落库与逐轮审计、预算快照、幂等、
取消、隔离与只读边界均符合 proposal / design / delta specs 契约，通过验收。
