## Why

后端所有 `created_at` / `updated_at` 都走 `DateTime(timezone=True)` + `server_default=func.now()`，但 `app/schemas/` 里没有任何时区归一化：开发 SQLite 的 `CURRENT_TIMESTAMP` 是 UTC，SQLite 与 MySQL 驱动取回来的都是不带偏移的 naive `datetime`，pydantic 原样输出裸串。生产 MySQL 的 `DATETIME` 不存偏移、值取决于会话时区，实机核对确认库存的也是 UTC，但生产界面整体偏 8 小时。客户端只能各自兜底，Web 2 处（`ReviewPage`、`SourceDetailDialog`）与原生 1 处（`sources/state.ts`）写了「缺时区就补 Z」，另外 7 个展示点直接 `new Date(裸串)`，移动端 `EntryDetailSheet` / `HistorySheet` 因此把刚结束的对话显示成「8 小时前」。同一个口径散在 10 个地方，任何新增展示点都可能再踩一次。

Web 端另有同源缺口：后端已返回 `SourceOut.has_processing_task`，移动端据此区分「等待处理」与「处理未启动」，但 Web 的来源列表与详情只看 `status`。等待处理却没有处理任务的来源不会被 Worker 轮到，在 Web 上却只显示「等待处理」，用户既看不出异常，也没有重试入口。

## What Changes

范围一·后端统一输出带时区时间：

- 所有对外响应 schema 统一继承新的响应基类，`datetime` 字段在输出前归一化到 UTC：naive 值按 UTC 解释，带偏移值换算成 UTC，JSON 统一为 UTC 带偏移（`Z`）。覆盖全部 schemas，不只 source；请求模型一并继承（当前无 datetime 请求字段，未来新增字段自动同口径）。
- 明确记录前提「naive 值按 UTC 解释」（SQLite 与 MySQL 都按 UTC 存储），解析/归一化异常必须留下可观测日志（warning + 堆栈并向上抛出），不得静默降级成裸串。
- 生产侧核对并固定 MySQL 会话时区为 UTC（`default-time-zone='+00:00'`），核对命令、结论与回滚方式写入 `design.md`。
- 兼容性：客户端「缺时区就补 Z」的检测遇到已带偏移的串会跳过，后端改成带 `Z` 不会二次偏移；客户端本轮收口时保留该检测。

范围二·客户端时间解析收口（一处实现，各处复用）：

- Web 新增共用时间工具，替换 7 个各写各的展示点：`ProjectContextPanel.tsx`、`EntryVersionHistoryDialog.tsx`、`EntryViews.tsx`、`KnowledgeAgentPage.tsx`、`ReviewPage.tsx`、`SourceDetailDialog.tsx`、`dialogue-workbench/WorkbenchApp.tsx`。
- 原生端收编到同一个共用工具：`EntryDetailSheet.tsx`、`HistorySheet.tsx`（`relativeTime` 不再把刚结束的对话显示成「8 小时前」）、`sources/state.ts` 的 `parseServerTime`。
- 各展示点保留自己的显示格式（Intl 选项不变），只统一「怎么把服务端时间串解析成时间点」。
- 验收：10 个收口点都有断言；`'2026-09-29T07:23:51'`（UTC）在东八区渲染为 15:23；带 `Z` / `+00:00` 的串不重复偏移。

范围三·Web 补齐「处理未启动」：

- Web 的 `SourcePayload` 补上后端已返回的 `has_processing_task`。
- `SourceList.tsx` 与 `SourceDetailDialog.tsx` 按移动端口径（`status === 'waiting' && !has_processing_task`）显示「处理未启动」并提供「重试处理」（`POST /api/sources/{id}/process`，409 视为状态本身正常，只刷新状态不报失败），文案与移动端一致。
- 失败重试（「重试」）与未启动重试（「重试处理」）两个入口保持区分，不合并成一个笼统入口；不得用等待时长阈值猜未启动。

## Capabilities

### New Capabilities

- `api-time-serialization`：后端对外响应 datetime 的时区口径——naive 按 UTC 解释、统一输出 UTC 带偏移、异常可观测、生产 MySQL 会话时区前提与客户端兼容边界。
- `client-time-parsing`：Web 与原生端解析服务端时间串的统一口径与复用要求——缺时区按 UTC、带偏移不二次偏移、各展示点共用同一实现。

### Modified Capabilities

- `source-management`：`Source 处理状态与触发` 补齐 Web 来源列表的「处理未启动」识别与「重试处理」入口、失败重试与未启动重试的区分、409 视为正常，并明确不使用等待时长阈值。
- `source-detail`：`来源详情查看` 补齐详情的「处理未启动」说明与就地「重试处理」入口。

## Impact

- `backend/app/schemas/`：新增响应基类模块，12 个 schema 文件的模型改继承该基类；`backend/tests/` 补时间口径与端点输出用例。无数据库结构变更、无新增端点。
- `frontend/src/lib/`：新增时间工具与来源状态口径模块，`api.ts` 的 `SourcePayload` 补 `has_processing_task`；7 个时间展示点、`SourceList.tsx`、`SourceDetailDialog.tsx` 与三个来源页面（`InboxPage`、`SourceHistoryPage`、`ProjectSources`）的触发处理 mutation 改为共用一处实现，相关组件测试补断言。
- `mobile/src/`：新增共用时间工具，`EntryDetailSheet.tsx`、`HistorySheet.tsx`、`sources/state.ts` 改为复用它，相关测试补断言。
- 生产运维：MySQL 需要一次性核对并固定 `default-time-zone='+00:00'`（仓库外操作，结论写入 `design.md`，本轮不新增代码侧会话时区设置）。
- 写入侧口径不变（仍由 `server_default=func.now()` 与 `onupdate=func.now()` 决定）；历史裸串数据不迁移，客户端继续按 UTC 解释。

## Non-Goals

- 不改数据库列类型、不做历史数据迁移，也不改写入侧时间口径。
- 不统一各展示点的具体显示格式（保留各自 Intl 选项与文案），本轮只统一解析与偏移。
- 不在移动端重复实现「处理未启动」（已由 `native-source-library` 覆盖）；不新增来源列表筛选、分页或状态筛选。
- 不改候选确认、审阅与处理 Worker 行为。
