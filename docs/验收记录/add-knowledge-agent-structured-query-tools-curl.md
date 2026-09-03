# 知识 Agent 结构化查询工具 API curl 验收记录

来源 change：`add-knowledge-agent-structured-query-tools`（任务 7.1）

验证日期：2026-09-03

## 环境与边界

使用隔离临时 SQLite 库 `/private/tmp/grove_structured_accept_20260902.db`，迁移到
`e9f0a1b2c3d4`，后端监听 `127.0.0.1:8031`。特性开关
`KNOWLEDGE_AGENT_STRUCTURED_QUERY_ENABLED=true`。

当前机器未配置真实文本模型。因此本次 curl 分成两类：

- 真实应用流程：移动端注册、Conversation、消息提交、waiting Run 取消，以及启用
  Worker 后真实触发 `structured_query_plan` 离线 fallback；
- 公开响应契约走查：在同一隔离库写入经过 Pydantic API schema 验证的 v1/v2 历史
  Run 快照和有界审计摘要，用 curl 验证精确统计、有限语义统计、非法计划拒绝与恢复
  的 Run/分页/可观测响应。这里不声称静态验收行来自真实模型；相应执行逻辑由
  `test_knowledge_agent_structured_query*.py`、Worker 恢复/取消测试和全量测试覆盖。

验收完成后已停止本地服务；临时数据库、Token 与响应文件均位于 `/private/tmp`，
未写入仓库。

## 启动命令

```bash
cd backend
DATABASE_URL="sqlite+aiosqlite:////private/tmp/grove_structured_accept_20260902.db" \
  .venv/bin/alembic upgrade head

DATABASE_URL="sqlite+aiosqlite:////private/tmp/grove_structured_accept_20260902.db" \
  PROCESSING_WORKER_ENABLED=false CONTEXT_WORKER_ENABLED=false \
  DIRECTORY_DRAFT_WORKER_ENABLED=false EMBEDDING_WORKER_ENABLED=false \
  KNOWLEDGE_AGENT_WORKER_ENABLED=true \
  KNOWLEDGE_AGENT_STRUCTURED_QUERY_ENABLED=true \
  .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8031
```

Bearer Token 通过真实移动端注册取得，以下命令以 `$AUTH_TOKEN` 代替，不记录原始
Token：

```bash
curl -X POST http://127.0.0.1:8031/api/auth/mobile/register \
  -H 'Content-Type: application/json' \
  --data '{"username":"accept_structured_20260902","password":"<redacted>"}'
```

结果：201，响应包含用户和非空 Token。

## 路由与认证状态

```bash
curl http://127.0.0.1:8031/api/knowledge-agent/conversations
curl http://127.0.0.1:8031/api/knowledge-agent/runs/1
curl http://127.0.0.1:8031/api/knowledge-agent/runs/1/entry-results
curl http://127.0.0.1:8031/api/knowledge-agent/runs/1/observability
```

四个请求均返回 401，不是 404，证明 Conversation、Run、结果分页与可观测路由已注册
且受现有认证保护。

带 Bearer 后的关键状态：

| 请求 | 结果 |
|---|---|
| `POST /api/knowledge-agent/conversations` | 201，创建 Workspace 范围对话 1 |
| `POST /conversations/1/messages` | 201，创建 waiting Run 1 |
| `POST /runs/1/cancel` | 200，Run 进入 cancelled |
| `GET /conversations` | 200 |
| `GET /conversations/1/messages?limit=30` | 200，关联 Run 同页返回 |
| `GET /runs/3`（精确 v2） | 200 |
| `GET /runs/2/entry-results?limit=1`（v1） | 200 |
| `GET /runs/3/entry-results?limit=1`（v2 第一页） | 200 |
| 使用返回游标读取 v2 第二页 | 200 |
| `GET /runs/7/observability`（恢复审计） | 200 |
| `GET /runs/8/entry-results?limit=6`（真实 fallback） | 200 |
| `GET /runs/8/observability`（真实 fallback） | 200 |

## 关键响应摘要

### 取消

真实 waiting Run 取消响应：

```json
{
  "id": 1,
  "status": "cancelled",
  "cancel_requested": true,
  "current_step": null,
  "entry_result": null,
  "structured_query_plan": null
}
```

取消没有提交迟到计划或结果。

### 精确统计、分组与列表

Run 3 返回公开的规范化计划摘要：`schema_version=v1`、`prompt_version=v1`，集合为
`main_types=[knowledge]` 与 UTC 闭开时间区间，输出固定为
`count → group_count(info_nature) → entries(updated_at desc, limit=2)`；响应不包含模型
原始输出、reason 或 prompt。

v2 结果关键字段：

```json
{
  "set_summary": {"completeness": "complete"},
  "count": {"value": 3, "completeness": "complete", "status": "completed"},
  "group_counts": [{
    "group_by": "info_nature",
    "buckets": [
      {"key": "experience", "count": 1},
      {"key": "unspecified", "count": 1}
    ],
    "completeness": "complete"
  }],
  "output_completeness": {
    "entries": "limited",
    "count": "complete",
    "group_count": {"info_nature": "complete"}
  }
}
```

精确 count=3 与只展示 2 张卡的列表边界相互独立，没有从卡片数量反推总数。

### 语义有限统计

Run 4 的 `semantic_query=防水经验`，集合、count 和 group 均为 `limited`；count 响应为
`{"value":2,"completeness":"limited","status":"limited"}`，warnings 明确说明
“只覆盖本次候选集合，不代表范围内全部知识”，没有包装成精确全集。

### v1/v2 历史分页

- v1：`schema_version=v1`、`returned_count=1`、`total_in_snapshot=1`、
  `has_more=false`；新增字段缺省不影响读取。
- v2 第一页：limit=1，`total_in_snapshot=2`、`has_more=true`，同时返回
  count=3 与各输出完整性。
- v2 第二页：使用服务端签名游标返回 Entry 102，`has_more=false`；count 仍为同一
  快照中的 3，未重新规划、查询或根据第二页数量变化。

### 非法计划与 fallback

- 非法计划响应（Run 6）：`structured_query_plan=null`、结果保持 v1，
  `fallback_summary` 记录 `provider=llm`、`model=accept-model`、
  `is_fallback=true` 和“未知字段或越权对象 id”校验错误。
- 真实离线 fallback（Run 8）：启用 Worker 后提交显式 entries 请求，Run 最终
  `completed`、`actual_result_mode=entries`、`structured_query_plan=null`、
  `entry_result.schema_version=v1`。可观测接口记录
  `purpose=structured_query_plan`、`provider=offline`、`model=null`、
  `is_fallback=true`、`error=未配置文本模型密钥`，没有静默降级。

### 恢复与审计

Run 7 可观测接口返回一次 planner 调用与三个固定顺序工具检查点：

1. `aggregate_entries` / count / completed；
2. `aggregate_entries` / group_count / completed；
3. `query_entries` / limited。

每项参数摘要都含 `tool_version=v1` 和独立 fingerprint；结果摘要只保存 count、桶数、
Entry id/数量和完整性，没有完整 Entry、Source 原文或 prompt。恢复复用的实际“不再次
调用 planner/已成功工具”由 `test_knowledge_agent_structured_query.py`、
`test_knowledge_agent_runner.py` 与 `test_knowledge_agent_read_tools.py` 的指纹恢复用例验证。

## 结论

相关端点在未登录时稳定返回 401、带有效 Bearer 时返回 200/201，不存在新增端点 404。
精确统计、limited 语义边界、v1/v2 历史分页、取消、非法计划、显式 fallback 与恢复审计
均符合本 change 的公开协议和可观测边界。
