# 设计：原生来源列表、只读详情与轮询

## 1. 数据来源与查询组织

- 列表直接使用既有 `GET /api/sources?limit=20`（可选 `unassigned=true`），不复用 Web 的 `GET /api/sources/query`：移动端本轮不做分页、搜索与状态筛选，`query` 的分页与总数对移动端无价值，而 `sources` 已按创建时间倒序并支持 `limit`。
- 详情读 `GET /api/sources/{id}`（整条最新状态与 `project_locked`）与 `GET /api/sources/{id}/candidates`，图片读 `GET /api/sources/{id}/attachments/{attachment_id}/file`。三者都走 `mobile/src/api.ts` 的 `request()`：它们是 JSON 或图片 GET，既有的 12 秒超时对元数据请求足够，不需要采集上传那条 90 秒通道。
- 图片来源用 `<Image source={{ uri, headers: { Authorization } }}>` 读取，避免为鉴权另开通道；放大查看用提供 `resizeMode="contain"` 的覆盖层，不引入图片库。
- 查询键集中在 `mobile/src/sources/queryKeys.ts`：列表按筛选值分键，详情按来源 id 分键。筛选切换即换键，会自然重新查询；TanStack Query 的全局默认 `staleTime: 0` 已满足「切换即取最新」。
- 拉取用 `ScrollView` 的 `RefreshControl` 触发 `refetch()`，不实现自定义下拉手势；刷新期间保留原条目，避免布局跳动。
- 列表查询的 `enabled` 同时依赖已登录与前台（见第 3 节），因此没有额外的手动生命周期管理。
- 采集提交结束回到入口页时主动失效来源库缓存：新来源此时是等待处理且有任务，列表重新取数后既能看到它，也会自动进入轮询状态；否则用户必须手动下拉才能看到刚提交的材料。

## 2. 等待处理未启动的判定

- 后端在 `SourceOut` 新增 `has_processing_task: bool`。实现上把 `backend/app/api/sources.py` 的 `_source_failure_info`（批量读 `ProcessingTask.source_id/status/error/retry_count`）扩展为 `_source_task_info`，第三次返回「存在任务的来源 id 集合」，因此**零额外查询、不产生 N+1**；列表、历史查询、创建、幂等命中、详情、修改与触发处理统一从 `_source_out` 带出该字段。
- 移动端判定式固定为 `status === "waiting" && has_processing_task === false`。不引入「等待超过 N 秒」启发式：Worker 积压时会误报，且阈值只能靠猜。若将来需要在没有任务字段的情况下判断，必须先回到 `design.md` 讨论。
- 该字段只用于「处理未启动」的识别与重试入口，不改变服务端状态机；重试直接调 `POST /api/sources/{id}/process`，该端点在无任务时会创建任务，是安全幂等的（并发同键由唯一索引兜底）。
- 字段是响应结构新增，不改数据库结构与迁移；Web 端不受影响，也仍不区分「有任务 / 无任务」，评估是否跟进留待与用户确认后另开 change。

## 3. 前台轮询

- **间隔取 4000ms。** 依据：处理链路包含抽取、项目路由与关系判定多次模型调用，正常耗时在数十秒量级；对话 Run 的 2000ms 是用户盯着逐字输出时的即时感要求，来源列表是后台任务状态，不需要同等密度；5000ms 以上会让「处理完成 → 列表刷新」的感知明显迟钝，而 4000ms 相比 2000ms 直接把移动网络请求量减半。一次采集常产生多条并列来源，这个折中优先保证「多条一起推进时反馈不迟钝」。
- 实现方式是列表查询的 `enabled: Boolean(token) && appActive` 加 `refetchInterval`：前台且 `hasActiveSources(data)`（存在 `waiting` 或 `processing`）时返回 4000，否则返回 `false`。两处判定都来自纯函数 `shouldPollSources`，便于单测。
- 进入后台时 `enabled` 变 false，定时请求立即停止且不会在后台补发；回到前台 `enabled` 变 true，TanStack Query 会立即查询一次，再按返回值决定是否继续轮询。不额外写 AppState 监听。
- 只显示「等待处理 / 处理中」状态文字与活动条数提示，不展示百分比进度。
- 详情打开时列表查询仍挂载，详情自身的查询使用同一间隔条件，保证详情里的状态与列表一致。

## 4. 界面形态

- 详情沿用原型的**全屏覆盖层**（`#detailOverlay`），不改路由：收集栏目仍是单页状态机（入口页 / 采集页 / 权限页）加若干覆盖层，详情与提交覆盖层同级。这样采集草稿与列表状态不会被路由切换打断，也与已归档的提交覆盖层形态一致。
- 列表作为独立组件挂到入口页，查询与操作状态集中在一个 `useSourceLibrary` 钩子中，由 `CaptureScreen` 托管，保证详情、列表与重试操作共享同一份数据，不需要跨组件回传刷新。
- 改归属与删除分别用 `Sheet`（底部弹层，复用 `knowledge-agent/components/ui.tsx` 的 `Sheet`），与原型 `#projectSheet` / `#deleteSheet` 对应。
- 复用的语义令牌与组件：`theme.ts`、`AppButton`、`Badge`、`Card`、`Sheet`。状态只用文字 + 颜色，不靠颜色单独表达。

## 5. 改归属与删除的口径

- **改归属**：打开弹层前用 `project_locked` 与 `status === "processing"` 预判，命中就不渲染项目列表、只给阻断说明（对应原型 `moveBlockedReason`）。预判未命中仍保留服务端 409 兜底，弹层内原样展示 `detail`。提交成功后 `PATCH` 响应返回时服务端已经跑完重新路由（`update_source` 在返回前 `await route_source/route_relations`），因此「正在重新路由」pending 态**就是这次请求的进行时间**：请求发出即标记、响应返回即清除，不需要额外轮询或用列表数据反推。
- **删除**：三类阻止中「处理中」「已被正式知识引用」都由服务端 409 拒绝，界面只做预判提示与原文透传；「有 pending 候选」由后端放行，界面用确认弹层做二次确认并写明「将一并移除这些候选」。没有 pending 候选时也保留确认弹层，但文案改为说明原始材料与候选都会移除且无法恢复。删除成功后关闭详情并刷新列表。
- 行为信号（`SIGNAL_PROJECT_DECISION`）由后端在改归属时记录，客户端不上报、也不展示推荐值。

## 6. 测试策略

- 纯逻辑放 `mobile/src/sources/state.ts`，直接单测：状态徽标四态 + 处理未启动、`done` 副状态四种组合与优先级、附件摘要、时间文案、失败原因与可重试判定、改归属预判两种阻断、删除三类阻止与 pending 二次确认文案、`shouldPollSources`（有活动条目才轮询、无活动条目返回 false、后台返回 false）。
- `mobile/src/sources/api.ts` 走 `global.fetch` mock：断言列表查询串（`limit=20`、`unassigned=true`）、4xx `detail` 原文透传为错误信息。
- 组件测试用 `@testing-library/react-native` + `QueryClientProvider`，`jest.mock` 掉 `@/src/auth` 与 `@/src/sources/api`：断言列表四态、筛选切换触发不同查询、失败原因与两个重试入口、详情只读（候选区域没有任何确认/拒绝/写入/归档按钮，`onPress` 型写入入口数量为 0）、改归属锁定预判不出选项、409 兜底展示原文、删除三类阻止与 pending 二次确认、轮询开关条件与后台停止。expo 与网络全部 mock，不依赖真机或模拟器。
- 后端 `backend/tests/test_sources.py` / `test_source_guards.py` 补 `has_processing_task` 的有任务 / 无任务两种取值，以及列表、详情、历史查询口径一致。

## 7. 已知取舍

- 列表固定 20 条、不做分页，用户看不到更早的来源；与原型和本轮范围一致，后续需要时再用 Web 的 `query` 端点或新端点补。
- 「每张一条」产生的多条并列来源在列表里只有时间相邻这一层关系，本轮不做同批分组线索。
- 「正在重新路由」是请求期状态，服务端重新路由如果很慢，弹层会长时间处于 pending；这是服务端同步路由的既有行为，本轮不改后端路由时机。
- 移动端开放删除会连带移除待确认候选，只靠二次确认保护，这是规划中用户明确接受的风险。
