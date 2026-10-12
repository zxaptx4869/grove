## 1. 规划工件

- [x] 1.1 四类工件齐备并通过 `openspec validate --all --strict`。

## 2. 后端：响应 datetime 统一 UTC 口径

- [x] 2.1 新增 `backend/app/schemas/base.py` 的 `ApiModel`：通配 `field_validator("*", mode="after")` 把 `datetime` 归一化到 UTC（naive 按 UTC、带偏移换算），`list` / `tuple` / `dict` 递归，其余原样返回；归一化失败记 warning 日志（含堆栈与字段信息）后向上抛出，不做静默兜底。验收：`backend/tests/test_schema_time_contract.py` 覆盖 naive、带 `+08:00`、嵌套模型与非法值四类行为，并断言失败路径有日志。
- [x] 2.2 `backend/app/schemas/` 全部模型改为继承 `ApiModel`（12 个文件，含请求模型），清理不再使用的 `BaseModel` 导入。验收：同一测试文件断言 `app/schemas/` 下每个模型都是 `ApiModel` 子类，新增模型漏继承即失败。
- [x] 2.3 端点级口径验证：沿用既有夹具断言来源列表 / 详情、项目、条目与知识 Agent Run 等响应的时间字段以 `Z` 结尾且不再是裸串（含嵌套的列表项）。验收：`backend/tests/test_sources.py`、`backend/tests/test_projects.py`、`backend/tests/test_knowledge_agent_api.py` 中新增断言。
- [x] 2.4 生产侧核对结论与前提写入 `design.md`（第 3 节）：`default-time-zone='+00:00'`、核对 SQL、回滚方式、不写代码级会话设置的理由。验收：设计文档可照做核对。

## 3. 生产 MySQL 与本地库时区核对

- [ ] 3.1（需用户在生产环境执行）生产 MySQL 核对 `SELECT @@global.time_zone, @@session.time_zone;` 为 `+00:00`，若偏离按运维项固定为 `default-time-zone='+00:00'` 后重启核对。验收：两项输出均为 `+00:00`（或 `UTC`）。
- [x] 3.2 本地开发库（SQLite）无需配置：已确认 `CURRENT_TIMESTAMP` 为 UTC，`select CURRENT_TIMESTAMP, datetime('now')` 返回 `2026-10-12 06:15:36`，与同刻 UTC 墙钟一致（东八区为 14:15）。验收：输出为 UTC 墙钟时间。

## 4. Web：共用时间工具与 7 处收口

- [x] 4.1 新增 `frontend/src/lib/time.ts`：`parseServerTime`（带 `Z`/`±HH:MM` 按原偏移、缺时区补 `Z`、非法值返回 `Invalid Date` 交由调用方兜底）与 `formatServerTime`（内部复用解析，选项与兜底文案由调用方传入）。验收：`frontend/src/lib/time.test.ts` 断言不带时区串与 `Z` / `+00:00` 串解析出的 epoch 相等，且 `timeZone: 'Asia/Shanghai'` 下 `'2026-09-29T07:23:51'` 渲染为 `15:23`。
- [x] 4.2 `ProjectContextPanel.tsx`、`EntryVersionHistoryDialog.tsx`、`EntryViews.tsx`、`KnowledgeAgentPage.tsx`、`ReviewPage.tsx`、`SourceDetailDialog.tsx`、`experiments/dialogue-workbench/WorkbenchApp.tsx` 的本地解析/补 Z 实现替换为共用工具，显示格式保持现状。验收：七个展示点的既有测试各补一条断言——同一时刻的裸串与带 `Z` 串渲染结果一致（无 8 小时偏移），`ReviewPage` 用显式 `Asia/Shanghai` 断言 15:23。

## 5. Web：来源「处理未启动」与重试入口

- [x] 5.1 `frontend/src/lib/api.ts` 的 `SourcePayload` 补必填 `has_processing_task: boolean`，同步既有 fixture（`SourceList.test.tsx` 的 `baseSource`、`InboxPage.test.tsx` 的等待处理样例）。验收：`npm run typecheck` 通过，等待处理样例仍渲染「等待处理」。
- [x] 5.2 新增 `frontend/src/lib/sourceStatus.ts`：`isProcessingNotStarted`（`status === 'waiting' && !has_processing_task`）、状态文案与配色（未启动用 `bg-warning-soft text-warning`）、`processingRetryLabel`（「重试处理」/「重试」）。验收：`frontend/src/lib/sourceStatus.test.ts` 覆盖等待处理有任务 / 无任务、处理中、完成、失败五种取值与两个重试文案。
- [x] 5.3 新增 `frontend/src/hooks/useSourceProcessingTrigger.ts`：封装 `POST /api/sources/{id}/process` 与 `queryKeys.sources` 失效，409 视为正常（不弹错误、改为失效刷新）。验收：`frontend/src/hooks/useSourceProcessingTrigger.test.tsx` 断言 409 不触发错误提示且会刷新、非 409 错误仍提示失败。
- [x] 5.4 `SourceList.tsx` 与 `SourceDetailDialog.tsx` 使用共用状态口径：未启动行显示「处理未启动」与「重试处理」，失败行仍为「重试」，等待处理且有任务的行不提供触发入口；详情在无候选时显示未启动说明卡片与就地「重试处理」。验收：`SourceList.test.tsx`、`SourceDetailDialog.test.tsx` 覆盖未启动徽标、两个重试入口区分、详情就地重试与 409 不报错。
- [x] 5.5 `InboxPage`、`SourceHistoryPage`、`ProjectSources` 的触发 mutation 改为复用同一 hook（分页失效键按页面传入）。验收：`InboxPage.test.tsx` 补「重试处理命中 409 不提示失败」断言，`useSourceProcessingTrigger.test.tsx` 覆盖 409 与其它错误两条分支；`SourceHistoryPage.test.tsx`、`ProjectSources.test.tsx` 只覆盖查询与渲染，改用共用 hook 后继续通过。

## 6. 原生端：时间解析收编

- [x] 6.1 新增 `mobile/src/serverTime.ts` 的 `parseServerTime`（与 Web 同口径），`mobile/src/sources/state.ts` 改为复用它（删除本地副本），`formatSourceTime` 行为不变。验收：`mobile/src/sources/state.test.ts` 既有断言继续通过，新增断言覆盖 `Z` / `+08:00` / 裸串三种串解析为同一时刻。
- [x] 6.2 `EntryDetailSheet.tsx` 的 `formatTime` 与 `HistorySheet.tsx` 的 `relativeTime` 改用共用解析。验收：`EntryDetailSheet.test.tsx` 与 `HistorySheet.test.tsx` 各补一条断言——不带时区的 UTC 串按 UTC 解析（历史「刚刚」不再显示「8 小时前」，详情更新时间与带 `Z` 串一致）。

## 7. 验证与收尾

- [x] 7.1 `cd backend && .venv/bin/pytest -q` 仅 `tests/test_embedding_retrieval.py::test_backfill_creates_missing_rows` 失败（`assert 32 == 1`，全量会话内的既有测试隔离问题；该用例单跑通过，且在未含本 change 的 pristine 检出上同样失败，与本 change 无关），其余全绿；`.venv/bin/ruff check .` 通过。`curl` 冒烟（独立 SQLite 库 + 全部 Worker 关闭）：注册 201、创建来源 201、来源列表 200、触发处理 200、来源详情 200，时间字段均为 `2026-10-12T06:15:19Z`（`datetime.fromisoformat(...).utcoffset() == 0`），未认证来源接口为 401 而非 404，`has_processing_task` 在存在处理任务时返回 `true`。
- [x] 7.2 `cd frontend && npm run lint && npm run typecheck && npm run test:run` 全绿。
- [x] 7.3 `cd mobile && npm run lint && npm run typecheck && npm test` 全绿。
- [x] 7.4 `openspec validate --all --strict` 通过。
- [x] 7.5 每段可验证修改做本地提交（中文 Conventional Commits），输出改动清单、验证命令与结果、未验证项与人工走查清单；**不推送、不合并、不归档**。

## 8. 人工走查（用户执行）

2026-10-12 用户完成走查，以下四项通过。

- [x] 8.1 Web 收集箱与来源历史：等待处理且未启动的来源显示「处理未启动」与「重试处理」，点击后状态刷新；等待处理且已有任务的来源仍显示「等待处理」且无触发入口；失败来源仍显示失败原因与「重试」。
- [x] 8.2 Web 来源详情的「处理未启动」说明与就地「重试处理」，以及重试命中 409（正在处理或已处理完成）时不出现失败提示。
- [x] 8.3 Web 各处时间显示：来源详情创建时间、审阅页来源时间、知识 Agent 对话更新时间、项目上下文生成时间、条目列表日期与版本历史时间，均为东八区下的真实时间（无 8 小时偏移）。
- [x] 8.4 原生端时间显示：条目详情更新时间、知识 Agent 历史相对时间（刚结束的对话显示「刚刚」）、来源列表时间文案。
- [x] 8.5 收集箱默认与文案（同轮走查）：进入收集箱默认选中「全部」，已归属项目的来源可见；筛选标签为「全部 / 未归属项目」；副标题与标题符合确认口径。

## 9. Web 收集箱默认展示全部来源（范围追加，2026-10-12）

范围追加理由：走查发现默认只显示「未归属」会让人误以为刚采集的来源没进来（AI 可能已自动归属项目）；本条为已实施行为补记规格与任务。

- [x] 9.1 收集箱默认筛选由「未归属」改为「全部」，筛选标签改为「全部 / 未归属项目」，副标题改为「先放进来，让 AI 来帮你提取知识、推荐项目、推荐目录，有空再到项目的确认台中采纳」；触发处理复用 5.3 的 `useSourceProcessingTrigger`。验收：`InboxPage.test.tsx` 覆盖默认选中「全部」与新文案。
- [x] 9.2 规格补齐：`specs/source-management/spec.md` 的「Source 列表」需求补「默认展示全部来源」与「筛选标签文案」。
- [x] 9.3 `openspec validate --all --strict` 通过。
