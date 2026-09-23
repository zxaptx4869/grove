# 设计：采集合同扩展与 Web 端接入

## 1. 幂等键的存储与唯一性

- 列类型与长度：`capture_key: Mapped[str | None] = mapped_column(String(128), nullable=True)`，允许为空，老数据与不带键的请求不参与唯一性（SQLite 与 MySQL 8 的唯一索引都把 NULL 视为互不相等，可存在多行 NULL）。
- 唯一性：使用**唯一索引** `uq_sources_workspace_capture_key (workspace_id, capture_key)`，而不是表级 `UniqueConstraint`。原因是 SQLite 不支持对既有表 `ALTER TABLE ADD CONSTRAINT`，唯一索引在 SQLite 与 MySQL 8 上语义等价，且可一次 `create_index` 直接落地。模型层同样用 `Index(..., unique=True)` 声明，保证测试用 `create_all` 与迁移结果一致。
- 唯一性范围是 Workspace，跨 Workspace 同键必须互不命中，因此索引第一列是 `workspace_id`。

## 2. 幂等命中路径

- 请求处理顺序：解析并校验 `capture_key`（strip 后空值视为未传，长度 1–128，超限 400）→ **在落盘之前**按 `(workspace_id, capture_key)` 查询已存在 Source → 命中则直接返回该 Source 并把响应码改写为 200 → 未命中才进入现有采集流程（读文件、落盘、建记录）。
- 状态码实现：路由装饰器仍声明 `status_code=201`，命中路径通过注入 `Response` 参数改写为 200；响应体始终是同一个 `SourceOut`，客户端按 `response.ok` 判断成功即可（Web `createSource` 已如此）。
- 并发同键：唯一索引兜底。`commit` 捕获 `IntegrityError` 后回滚、回查已存在记录并返回 200；本次调用已经通过 `storage.save()` 写入的文件路径全部 `storage.delete()` 清理，沿用文件校验失败分支现有的清理写法。回查仍取不到记录时按冲突报错（不应发生），避免静默吞并。
- 命中返回时必须复用 `_load_source_out`，保证失败信息等字段与其它路径一致。

## 3. 标题覆盖

- `title` 作为可选 `Form` 字段：`strip()` 后为空视为未传；非空则截断 255 后作为新 Source 标题。
- 默认值计算收敛为一条：`files` 非空时取第一个图片文件名，否则取 `_text_title(text)`；最终标题 `= 覆盖值 or 默认值`。既有的后缀、MIME、大小、张数校验顺序与文案不变。

## 4. `SourceOut` 失败信息

- 字段命名：`failure_reason: str | None` 与 `retry_count: int = 0`（对齐 `ProcessingTask.retry_count` 与现有 `project_locked` / `evidence_entry_count` 风格）。
- 口径：`failure_reason` 仅当任务 `status == failed` 且 `error` 非空时给出，其它状态（`waiting` / `processing` / `done`）与无任务时均为 `null`，避免把历史错误当成当前问题；`retry_count` 有任务时取实际值，无任务为 0。
- 批量读取：新增 `_source_failure_info(db, source_ids)` 做一次 `select(ProcessingTask.source_id, ProcessingTask.status, ProcessingTask.error, ProcessingTask.retry_count).where(ProcessingTask.source_id.in_(source_ids))`，返回两个字典；与现有 `_source_state_counts` 的批量模式一致，列表与历史查询只多一次查询，不随条数增长。
- `_source_out()` 增加两个入参；`_load_source_out`、`list_sources`、`query_sources`、`create_source`（含幂等命中路径，走 `_load_source_out`）、`get_source`、`update_source`、`trigger_processing` 全部接入，保持字段一致。

## 5. Web 端 `capture_key` 承载

- `SourceCapture` 用 `useRef<string | null>` 保存当前采集动作的键：提交时若为空则 `crypto.randomUUID()`，`FormData` 追加 `capture_key`。
- 键的生命周期：**提交失败保留**（弱网连续重试复用同一个键，第一次其实成功、客户端超时后再点提交不会产生第二条来源）；**提交成功后在 `reset()` 里清空**（用户主动再采一次即使内容相同也新建）；**草稿输入变化（图片、附加文字、补充说明、项目）时清空**，因为那已是一次全新采集动作而不是同一次重试。
- `createSource` 已按 `response.ok` 判断成功，200/201 都能正常返回 Source，无需改动，也不需要在响应里区分命中与否。
- 幂等命中后的处理触发：`trigger_processing` 对 `processing` 与 `done` 返回 409 且不改状态，对 `waiting` 保持 `waiting`、不新增任务，因此重复触发不会破坏状态或产生重复执行。Web 端保留现有行为（`triggerProcessing` 失败只提示「来源已保存，但处理启动失败」），不额外加判断；该结论同步写入 `processing-task` 规格。

## 6. 迁移

- 单次迁移：`add_column("sources", capture_key)` + `create_index(..., unique=True)`；`downgrade` 反向 `drop_index` + `drop_column`。`create_index` 在 SQLite 与 MySQL 8 均可执行，不依赖方言专属能力。
- 在已有数据的库上可执行：新列可空且不回填，唯一索引对全 NULL 历史行成立。
