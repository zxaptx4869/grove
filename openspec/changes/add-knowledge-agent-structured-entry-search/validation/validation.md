# 验证记录（任务组 8）

> 日期：2026-09-01；分支：`codex/add-knowledge-agent-structured-entry-search`；
> 环境：macOS 本机开发环境，无运行中的 MySQL 8 / Docker 守护进程 / iOS 模拟器。

## 1. 自动化测试与静态检查

### 后端（`backend`）

| 检查项 | 结果 |
|---|---|
| `backend/.venv/bin/pytest backend/tests` | 543 passed（基线 497，本 change 新增 46） |
| `backend/.venv/bin/ruff check backend/app backend/tests` | All checks passed |
| 新增测试文件 | `test_knowledge_agent_result_protocol.py`（协议/迁移）、`test_knowledge_agent_result_mode_route.py`（路由）、`test_knowledge_agent_entry_search.py`（查找）、`test_knowledge_agent_entry_results_api.py`（分页） |

### 移动端（`mobile`）

| 检查项 | 结果 |
|---|---|
| `npx jest --runInBand` | 11 suites / 122 tests passed（基线 101，本 change 新增 21） |
| `npm run lint` | 通过 |
| `npm run typecheck` | 通过 |
| Jest 退出 | 正常退出，无 `--forceExit`，无未解释 act/open handle warning |
| iOS Expo export | 成功（metadata.json） |
| Android Expo export | 成功（metadata.json） |

## 2. curl 真实 API 走查（开发后端，离线模型环境）

数据准备：注册 → 建项目/节点 → 建来源 → 处理 → 候选归档为正式 Entry → 建对话。

| 场景 | 方法/路径 | 结果 |
|---|---|---|
| 未登录访问结果分页 | `GET /api/knowledge-agent/runs/1/entry-results` | 401 |
| 提交显式 entries | `POST .../messages`（`result_mode=entries`） | 201，`request_result_mode=entries` |
| Run 轮询 | `GET /runs/2` | 200，`actual_result_mode=entries`、`entry_result` 首屏、`completeness=complete`、`matched_fields=[title,content,source]` |
| 结果分页 | `GET /runs/2/entry-results?limit=6` | 200，`returned_count=1`、`has_more=false` |
| 篡改游标 | `GET ...?cursor=garbage` | 400 `无效的结果游标` |
| answer Run 读取结果 | `GET /runs/3/entry-results` | 404 `该 Run 没有结构化结果` |
| auto 路由（离线模型） | 提交不带 `result_mode` | Run `request=auto`、`actual=answer`，`fallback_summary` 含 `result_mode_route`（provider=offline、is_fallback=true、error=未配置文本模型密钥） |
| 可观测记录 | `GET /runs/2/observability` | 200，`structured_entry_search` 工具调用 + embedding/rerank 模型调用（离线 fallback） |
| 跨用户越权 | 第二用户 `GET /runs/2/entry-results` | 404 |
| 取消已终态 Run | `POST /runs/2/cancel` | 200，状态保持 `completed`（幂等） |

### 模型可观测说明

本环境未配置真实模型密钥，所有模型阶段（上下文决策、结果形态路由、回答模式路由、
embedding、rerank、回答）按设计走离线 fallback 并写入 provider/model/is_fallback/error。
`result_mode_route` 的 fallback 在 Run 聚合摘要与 observability 端点均可识别；
正常空结果不误报 fallback（工具状态 ok/empty 不计入降级）。真实模型质量与路由命中率
需要用户在配置密钥后的真实环境走查（见未验证项）。

## 3. 迁移验证

| 项目 | 结果 |
|---|---|
| fresh SQLite `alembic upgrade head` | 通过；`knowledge_agent_runs` 含 `request_result_mode`(VARCHAR(8))、`actual_result_mode`(VARCHAR(8))、`entry_result_json`(TEXT) |
| downgrade→upgrade 往返 | 通过；字段删除后重建，历史 Run 行保留（新字段回空按旧行兼容） |
| 旧行兼容 | 三个新字段为空时 `run_out` 输出 `auto / answer / 无结果` |
| JSON 字节上限 | `knowledge_agent_result_json_bytes_limit=60000 < MySQL TEXT 65535`，序列化前确定性截断并标记 limited |
| MySQL 8 运行时迁移 | **未验证**（环境无 MySQL 8 与 Docker 守护进程）；已通过 String(8)/Text、batch_alter_table 与字节上限做兼容设计，离线 SQL 生成受既有迁移的 `sa.inspect(bind)` 阻断 |

## 4. 截图与设备走查

- **截图：未生成**。本环境无可用 iOS 模拟器/Android 设备，无法在真实 RN 页面保存
  390×844、360×800、412×915 截图。
- 设备级键盘、安全区、动态字体、底栏与读屏走查：**未验证**，需用户在真实 App 验收。
- 替代证据：Expo export（iOS/Android）成功；组件测试覆盖 44×44 触控高度、
  辅助名称、长标题/摘要、30 条分页、跨项目、空态、分页失败保留、详情更新/404、
  无多选/修订/批量文案；`EntryResultsCard`/`EntryResultSheet` 在 Jest 渲染通过。

## 5. 独立代码审查结论（任务 8.8）

审查重点与结论：

| 重点 | 结论 |
|---|---|
| 范围与 Workspace 隔离 | 搜索只从 Run 固化的 owner/Workspace/项目加载正式 Entry；项目范围在装配时再次复验；跨用户/Workspace 由 `get_owned_run` 404 兜底 |
| result_mode/answer_mode 优先级 | 上下文决策 clarify 先结束；显式 answer/entries 跳过路由；entries 跳过回答模式、调查、Evidence 与回答模型，`actual_answer_mode` 保持空、请求模式仍可审计 |
| JSON 大小与 MySQL 8 | 候选 50 / 持久化 30 / 页 6-12 / 摘要 240 字 / 字节上限 60000；超限确定性丢弃并标记 limited |
| 游标篡改 | 游标 HMAC 签名并绑定 run/owner/workspace/schema/offset；篡改、跨 Run、越界返回 400 |
| rollback 后 ORM 状态 | entries 执行图在提交后不再读取 `updated_at` 等 onupdate 列（快照时间用应用时钟）；候选确认路由的过期对象修复已由前置提交覆盖 |
| 工作集不推进 | entries 终态只写兼容摘要 + 快照 + 活动槽释放，不创建输出上下文版本；测试断言版本计数不变 |
| 旧客户端兼容 | 提交未带 `result_mode` 按 auto；旧 Run/旧响应缺字段按 answer 渲染 AnswerCard；移动类型对结果形态/entryResult 字段可选化 |
| 分页稳定性 | 快照不可变、分页只读同一 JSON；客户端按 entry id 去重追加；失败保留已加载项不重提问题 |
| 移动长列表与键盘 | 结果行扁平分隔、无嵌套卡片；键盘避让沿用既有唯一负责人；真实设备走查未验证 |

审查中发现并修复的问题：
1. `structured_entry_search` 工具记录缺 `total` 字段导致有结果时误标 `empty`；
   已补 `total` 并加断言（工具状态 ok）。
2. 快照指纹缺失时详情 Sheet 不得误报「当前内容与结果一致」；改为仅在可比对时展示。
3. 移动端结果形态/entryResult 字段改为可选，强化旧响应兜底。
4. 真实重排成功返回空结果时曾按召回顺序重新加入全部候选；现只在模型降级或错误时兜底，并补“成功空重排保持为空”测试。
5. 模式纠正曾依赖客户端已加载原用户消息，并使用当前历史/范围/工作集重新提交；现携带 `source_run_id`，由服务端恢复原问题、独立问题、上下文决策、生成时范围、上下文模式与输入工作集，同时覆盖跨 Conversation 拒绝、来源消息未加载、网络重试和冲突测试。

## 6. 未验证项与剩余差异

- MySQL 8 运行时迁移与分页/并发终态语义：未验证（无环境）。
- 真实 AI provider 下的结果形态路由命中率、embedding/rerank 质量：未验证。
- 真实 iOS/Android 设备截图、键盘、安全区、动态字体、底栏与读屏：未验证。
- 有意偏离：见 `validation/visual-baseline.md`「已实现基线核对」；
  对话内结果容器、指纹比对、LCS 匹配线索为本 change 相对原型的新增基线。
- 剩余差异：无已知功能性缺陷；Run/消息首屏响应仍携带完整有界快照，已作为性能优化登记。等待用户在真实 App 手动验收自动路由、结果卡、分页、详情与模式纠正。
