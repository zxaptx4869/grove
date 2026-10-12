## Context

已确认的事实（本 change 直接采用，不再重新论证）：

- 后端所有 `created_at` / `updated_at` 走 `DateTime(timezone=True)` + `server_default=func.now()`（`app/models/`，写入口径本轮不变）；`app/schemas/` 里没有任何时区归一化，客户端拿到的是不带时区的裸串。
- 开发 SQLite 的 `CURRENT_TIMESTAMP` 是 UTC；生产 MySQL 的 `DATETIME` 不存偏移、值取决于会话时区，实机核对确认生产库存的也是 UTC（未修复的生产界面偏 8 小时）。
- 客户端目前各自解析服务端时间，共 10 个展示点：Web 7 处（`ProjectContextPanel.tsx`、`EntryVersionHistoryDialog.tsx`、`EntryViews.tsx`、`KnowledgeAgentPage.tsx`、`ReviewPage.tsx`、`SourceDetailDialog.tsx`、`experiments/dialogue-workbench/WorkbenchApp.tsx`），原生端 3 处（`knowledge-agent/components/EntryDetailSheet.tsx`、`HistorySheet.tsx`、`sources/state.ts` 的 `parseServerTime`）。其中只有 Web 的 `ReviewPage`、`SourceDetailDialog` 与原生 `sources/state.ts` 写了「缺时区就补 Z」，其余直接 `new Date(裸串)`。
- 后端已返回 `SourceOut.has_processing_task`（`add-native-source-library`，2026-10-12 归档），移动端已据此识别「处理未启动」；Web 未使用该字段。

由此确立的前提：**naive 时间值按 UTC 解释**（SQLite 与生产 MySQL 存量值都是 UTC），后端序列化统一输出 UTC 带偏移，客户端解析保留「已带偏移则跳过」的检测以兼容历史裸串。

## Goals / Non-Goals

**Goals:**

- 后端一处收口：所有对外响应 `datetime` 归一化为 UTC 带偏移，新增 schema 字段自动同口径，异常可观测。
- 客户端一处实现、各处复用：Web 与原生端各一份共用时间解析工具，替换 10 个展示点。
- Web 来源列表与详情按移动端口径补齐「处理未启动」与「重试处理」，409 视为正常。
- 生产 MySQL 会话时区前提被核对、固定并记录，避免写入侧落本地墙钟时间。

**Non-Goals:**

- 不改数据库列类型与写入侧口径，不迁移历史数据。
- 不统一各展示点的显示格式与文案。
- 不新增代码级的 MySQL 会话时区设置（理由见决策 3）。
- 不改处理 Worker、候选确认与审阅流程。

## Decisions

### 1. 后端用「schema 基类 + 通配校验器」收口，而不是逐字段改类型或自定义序列化器

新增 `app/schemas/base.py`，提供 `ApiModel(BaseModel)`：以 `@field_validator("*", mode="after")` 对每个字段做归一化——`datetime` 走 UTC 归一化（naive 补 UTC，带偏移 `astimezone(UTC)`），`list` / `tuple` / `dict` 递归处理，其余原样返回。`app/schemas/` 下 12 个文件的模型全部改为继承 `ApiModel`（含请求模型；当前没有任何 datetime 请求字段，未来新增自动同口径）。

- 通配 `field_validator("*")` 在 pydantic 2.13 上可用，`model_dump(mode="json")` 对 UTC 值输出 `...Z`，python 模式仍返回带 UTC 的 `datetime` 对象，内部逻辑不受影响；OpenAPI 里字段仍是 `format: date-time`（用 `PlainSerializer` 会把 JSON schema 退化成纯 `string`，故不采用）。
- 相比逐字段改成 `Annotated[datetime, AfterValidator(...)]`：免去 30 余处手工替换，且新增字段天然同口径；代价是请求模型一并继承，当前无实际行为差异。
- 不使用 `AwareDatetime`：它只做校验不做归一化，naive 值会直接报错，而库里存量就是 naive。
- 归一化失败的异常先记 warning 日志（含堆栈、字段名、原值）再向上抛出，符合「可观测、不静默降级」；pydantic 解析失败本身会带字段路径报错，不做兜底替换。

覆盖方式：`backend/tests/test_schema_time_contract.py` 断言 `app/schemas/` 下所有模型都是 `ApiModel` 子类（防新增模型漏继承），并覆盖 naive / 带偏移 / 嵌套 / 非法值四类行为；端点级断言放在既有来源与知识 Agent 测试里。

### 2. 前端共用工具只统一解析，不统一格式

- Web 新增 `src/lib/time.ts`：`parseServerTime(value)`（带 `Z` / `±HH:MM` 按原偏移，缺时区补 `Z`）与 `formatServerTime(value, options, fallback)`（内部走 `parseServerTime`，各点自己传 Intl 选项与兜底文案）。7 个展示点改为调用它，显示格式保持现状（含 `ReviewPage` 显式的 `Asia/Shanghai`）。
- 原生新增 `src/serverTime.ts`：`parseServerTime` 从 `sources/state.ts` 迁出，`sources/state.ts`、`EntryDetailSheet.tsx`、`HistorySheet.tsx` 复用它；`HistorySheet` 的 `relativeTime` 因此在裸串与带 `Z` 串下都能算对，刚结束的对话不再显示「8 小时前」。
- 保留「已带偏移则跳过补 Z」的检测：后端改成带 `Z` 后不会二次偏移，历史裸串（旧数据、直接读库的调试路径）仍按 UTC 解释。
- 不做全局 `fetch` 拦截改写时间串：响应里时间字段位置分散、类型不可靠，拦截层很难保证不漏不误；共用解析工具更窄且可被逐点断言。

### 3. 生产 MySQL 时区按运维项固定，不在本轮写代码级会话设置

核对与固定方式：MySQL 配置 `[mysqld] default-time-zone='+00:00'`，部署核对执行 `SELECT @@global.time_zone, @@session.time_zone;`，两项都应为 `+00:00`；回滚即改回原值并重启。结论：存量数据已经是 UTC，固定会话时区不改变存量时间语义，只保证后续 `func.now()` 不会因会话时区变化写入本地墙钟时间。

不采用「连接事件里 `SET time_zone = '+00:00'`」或 DSN `init_command`：仓库内没有 MySQL 环境与回归用例，这两条路径都无法在本轮验证，写进生产连接初始化一旦失败会导致连不上库；而 `default-time-zone` 是数据库侧配置，可由核对命令直接验证。若后续需要应用侧强保证，另开 change 带真实 MySQL 用例再做。

### 4. Web「处理未启动」共用一处派生，重试入口共用一处 mutation

- 新建 `src/lib/sourceStatus.ts`：`isProcessingNotStarted(source)`（`status === 'waiting' && !has_processing_task`）、状态文案与配色、`processingRetryLabel(source)`（未启动 →「重试处理」，失败 →「重试」）。`SourceList.tsx` 与 `SourceDetailDialog.tsx` 共用，替换两份重复的 `STATUS_LABELS` / `statusClass`。未启动配色用 `bg-warning-soft text-warning`，与移动端 risk 色值（`#9A6419` / `#FFF5DF`）一致。
- 新建 `src/hooks/useSourceProcessingTrigger.ts`：封装 `POST /api/sources/{id}/process` + 失效 `queryKeys.sources`，`ApiError.status === 409` 视为状态本身正常（不弹错误、改为失效刷新，与移动端一致），其余错误沿用既有 toast。`InboxPage`、`SourceHistoryPage`、`ProjectSources` 三个页面的触发 mutation 改为复用它（`SourceHistoryPage` 额外传自己的分页失效键），详情弹窗内部也用它，免去 prop 透传。
- 详情弹窗的空候选分支补「处理未启动」卡片（标题「处理未启动」、正文「这条来源没有处理任务，不会被自动处理。」、按钮「重试处理」）。移动端详情只有文案提示「回到列表点「重试处理」」，Web 就地提供按钮是**有意偏离**：Web 详情是弹窗，就地重试少一次关闭与定位动作，文案与状态名仍与移动端一致。
- 失败重试与未启动重试保持两个入口：失败行显示失败原因与「重试」，未启动行显示「处理未启动」与「重试处理」；等待处理且已有任务的来源不提供任何触发入口。同时把主规格里「对等待处理提供「开始处理」」的老表述改为上述口径——实现从未有过「开始处理」按钮，等待处理且已有任务的来源由 Worker 自动接手，这次顺带纠正这处规格与实现的既有偏差。

## Risks / Trade-offs

- [生产 MySQL 会话时区核对（已完成）] → 2026-10-12 在生产执行 `SELECT @@global.time_zone, @@session.time_zone, @@system_time_zone, NOW(), UTC_TIMESTAMP();`，输出 `SYSTEM  SYSTEM  UTC  <同一时刻>  <同一时刻>`：系统时区为 UTC 且两个时间函数完全相等，库口径等价于 UTC，未做参数变更。宿主与容器时区本就是 UTC，因此没有再显式覆盖 `default-time-zone`；若后续更换宿主、容器镜像或迁移实例，需要重跑该核对命令确认。
- [归档器不允许在同一需求内删除场景] → 主规格「Source 处理状态与触发」中已废弃的「开始处理」场景保留原场景名、改写为新口径（等待处理不再提供手动「开始处理」），需求正文同步删掉「对等待处理提供「开始处理」」的老表述；保留场景名是归档器的约束，语义以改写后的正文与场景内容为准。
- [通配校验器让请求模型一并继承] → 当前请求模型没有 datetime 字段，行为差异为零；测试断言模型继承关系与四类行为，防止未来无声变化。
- [pydantic 在响应序列化时报错会变成 500] → 归一化失败先记 warning 再抛出，日志可定位；不静默返回裸串是刻意的取舍。
- [Web 测试的等待处理样例缺 `has_processing_task` 会翻转成「处理未启动」] → 同步更新既有 fixture（`SourceList.test.tsx` 的 `baseSource`、`InboxPage.test.tsx` 的等待处理样例），并把该字段设为 `SourcePayload` 必填，避免漏传。
- [东八区断言依赖运行机器时区] → 共用工具的断言用 epoch 相等（与机器时区无关）+ 显式 `timeZone: 'Asia/Shanghai'` 断言 15:23；组件级断言与既有 `SourceDetailDialog.test.tsx` 同口径。

## Migration Plan

1. 后端先落地：新增基类并统一切换继承，跑 `pytest` + `ruff` 后本地提交。
2. 客户端收口解析工具与展示点，再补 Web「处理未启动」，各自跑对应 lint / typecheck / 测试后分阶段提交。
3. 生产部署时在变更窗口执行 MySQL 时区核对与固定，随后用来源详情创建时间与知识 Agent 对话时间人工验收。
4. 回滚：后端与客户端各自可独立回滚（后端回滚后客户端解析工具仍按 UTC 解释裸串，行为与修复前兼容）；MySQL 配置改回原值并重启即可，存量数据不变。
