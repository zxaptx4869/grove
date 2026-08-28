# 知识 Agent 连续追问 API curl 验证记录

来源 change：`add-knowledge-agent-continuous-follow-up`（任务 7.2）
验证日期：2026-08-28
环境：本地开发后端，SQLite（`backend/grove.db`，迁移到 `b1c2d3e4f5a6`），端口 8012，
进程内 Worker 开启；未配置模型密钥，因此真实模型阶段全部走确定性/离线降级，
正好用于验证「决策可见 + 安全降级」路径。

## 启动与迁移

```bash
cd backend
DATABASE_URL="sqlite+aiosqlite:///./grove.db" .venv/bin/alembic upgrade head
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8012
```

## 走查中发现并修复的真实缺陷

首问执行时 `knowledge_context_versions` 插入报 `NOT NULL constraint failed: id`：
迁移里主键用纯 `BIGINT`，SQLite 不会把它当作 `INTEGER PRIMARY KEY` rowid 别名，
因此不自动生成 id。修复：

- 新迁移 `b1c2d3e4f5a6` 的 `_bigint()` 改为
  `sa.BigInteger().with_variant(sa.Integer(), "sqlite")`；
- 同一缺陷也存在于已归档的底座迁移 `a0b1c2d3e4f5`
  （fresh SQLite 经 alembic 建表后 `knowledge_agent_runs.id` 为 BIGINT），
  一并修复为与 ORM 一致的类型，并在迁移测试中增加无显式 id 的自增回归断言。

## 验证结果（HTTP 状态码与关键字段）

| 步骤 | 请求 | 结果 |
|---|---|---|
| 未登录访问 | `GET /api/knowledge-agent/conversations` | 401 |
| 注册用户 | `POST /api/auth/register` | 201 |
| 创建对话 | `POST /api/knowledge-agent/conversations` | 201 |
| 建项目/节点/来源 | `POST /api/projects`、`/nodes`、`/sources` | 201/201/201 |
| 处理来源并确认 Entry | `POST /api/sources/92/process`、`/api/candidates/116/archive` | 200/200 |
| 首问（auto） | `POST .../messages`（walk-1b） | 201，`request_context_mode=auto` |
| 轮询首问 Run | `GET /api/knowledge-agent/runs/13` | 200：`new_topic`（离线降级 `context_degraded=true`）、输出版本 1（空主题）、回答 `failed`（回答模型不可用） |
| 自动追问（auto） | walk-2 | 201；Run 14：`new_topic`、输入版本 1、输出版本 2 |
| 强制继续（continue） | walk-3 | 201；Run 15：`continue`、独立查询 `为什么不能提前放水？：为什么不能提前放水？`、输入版本 2、无输出版本（无有效引用不推进） |
| 强制新话题（new_topic） | walk-4 | 201；Run 16：`new_topic`、提交时关闭旧活动版本、输出版本 3（空主题） |
| 对话摘要 | `GET .../conversations/13` | `active_topic_label=庭院树木冬季怎么养护？`、版本 3、0 条 Entry |
| 范围切换 | `PATCH .../conversations/13/scope` | 200；`active_topic_label=None`、活动版本关闭 |
| 无工作集强制继续 | walk-5 | 201；Run 17：`clarify`、回答状态 `clarification`、无版本 |
| 幂等重试（改模式） | 重发 walk-3 带 `new_topic` | 200；返回原 Run 15，模式仍为 `continue` |
| 取消 waiting Run | walk-7 提交后立即 `POST /runs/19/cancel` | 200；`cancelled`、无回答、无决策 |

## 可观测性与消息上下文

Run 13 observability：

```text
tools:  working_set_seed:empty, search_confirmed_knowledge:ok,
        read_entries:ok, read_source_evidence:ok
models: context_decision(offline, fallback), embedding(doubao, fallback),
        rerank(offline, fallback), answer(offline, fallback)
```

消息列表返回生成时的模式、决策、输入/输出工作集版本：

```text
walk-1b auto | new_topic | in: None | out: 1
walk-2   auto | new_topic | in: 1    | out: 2
walk-3   continue | continue | in: 2 | out: None
walk-4   new_topic | new_topic | in: 2 | out: 3
walk-5   continue | clarify | in: None | out: None
walk-7   auto | None（提交后即取消） | in: 4 | out: None
```

## 引用重新核验与真实模型路径

本次走查没有配置模型密钥，回答模型离线降级，无法通过 curl 生成真实引用；
「工作集 Entry 每轮重新读取 Attachment 并生成本 Run Evidence、历史 Evidence
句柄拒绝复用、来源变化后不沿用旧 quote」由自动化测试覆盖：

- `test_runner_continue_merges_seed_and_new_discovery`（本轮新 Evidence + 输出工作集）；
- `test_runner_historical_evidence_rejected_and_context_kept`（历史句柄丢弃、上下文不推进）；
- `test_runner_continue_seed_deleted_records_unavailable`（种子删除只记录不可用）。

## 备注

- 走查期间发现并修复 SQLite 迁移 BIGINT 自增缺陷（见上），验证前先
  `downgrade a0b1c2d3e4f5` 再 `upgrade head` 重建两张新表；
- 修复前失败的首问 Run（walk-1）保留在开发库中作为异常记录，人工验收后可清理；
- 未配置模型密钥时 `auto` 分类按设计显式降级为 `new_topic` 且
  `context_degraded=true`，不会静默沿用旧工作集。

## MySQL 8 真实验证（7.3）

环境：一次性临时 MySQL 8.0.45 实例（`mysqld --no-defaults --initialize-insecure`，
独立数据目录与端口 33063，验证后已关闭并删除目录）。沙箱内初始化 mysqld 会触发
signal 11，需在沙箱外运行；本机 Homebrew `mysql@8.0` 服务当前未运行，不影响验证。

```bash
/opt/homebrew/opt/mysql@8.0/bin/mysqld --no-defaults --initialize-insecure --datadir=<tmp>
/opt/homebrew/opt/mysql@8.0/bin/mysqld --no-defaults --datadir=<tmp> \
  --port=33063 --socket=<tmp>/mysql.sock --bind-address=127.0.0.1 --mysqlx=0
DATABASE_URL="mysql+asyncmy://root@127.0.0.1:33063/grove_mysql_test?charset=utf8mb4" \
  .venv/bin/alembic upgrade head
```

### 验证结果

| 项目 | 结果 |
|---|---|
| 迁移链 `a0b1c2d3e4f5 → b1c2d3e4f5a6` | 成功；新表与 Run 新列均存在，id 为 BIGINT（MySQL 正确类型） |
| `knowledge_context_versions` 单活动约束 | 第二个 `(conversation_id, 'active')` 报 `Duplicate entry '1-active'`（1062） |
| 多终态 NULL | 终态置 `active_slot=NULL` 后可连续插入多个历史版本（验证库内共 4 个版本） |
| `knowledge_agent_runs` 单活动约束 | 第二个 active 报 `Duplicate entry '1-active'`（1062） |
| 运行中步骤可见 | 会话 B 提交 `current_step='search'` 后，新会话读到 `search` |
| 跨事务取消 | 长事务快照与同事务重读均为 0；新短会话读到已提交的 `cancel_requested=1`（与 Runner 短会话检查一致） |
| 崩溃恢复字段 | Run 可写 `input_context_version_id`（外键指向版本 3）并保留 `request_context_mode='continue'` |

结论：MySQL 8 下迁移、单活动版本约束、多终态 NULL、运行中步骤可见与跨事务
取消语义均符合 design 第 7 条（短会话读写）与 specs 的契约。
