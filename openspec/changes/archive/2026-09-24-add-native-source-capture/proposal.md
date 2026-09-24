## Why

移动端「收集」栏目目前只有 `Unavailable` 占位，用户最常用的三条采集路径（拍照、相册选图、粘贴文字）在原生端无法入库；而移动端最需要的弱网重试、多选拆条与部分失败重试也没有承载。后端采集合同（`capture_key` 幂等键、可选 `title`、`SourceOut` 失败信息）已在 `add-source-capture-idempotency` 中实现并归档，原生端可以直接接上。本 change 只做**采集入口与上传链路**，把这三条路径在原生端真正打通。

## What Changes

- 收集栏目替换 `Unavailable` 占位，提供三入口横排：相机（系统相机拍 1 张）、相册（先选「每张一条」或「多张合并一条」，再多选 1–5 张）、文本（输入或从剪贴板填入）。
- 采集表单只有「补充说明」与「所属项目」两个字段，默认未归属；不提供 Web 的「附加文字内容」，图片采集不再携带正文。
- 图片在客户端统一压成 jpg（长边 2048、quality 0.8），同时规避 HEIC 与单张 10MB 上限。
- 新增独立 multipart 上传通道，不复用 `mobile/src/api.ts` 的 `request()`（其固定 JSON 头与 12 秒超时）；上传使用独立更长超时，失败由用户显式重试。
- 幂等键按「批次 UUID : 序号」派生：同一张重试复用同一键，用户重新采集生成新批次；「每张一条」按张串行提交并显示「正在上传 N 张中的第 M 张」，提交成功后逐条 `POST /api/sources/{id}/process`。
- 采集结果自包含反馈：进行中 / 全部成功 / 部分失败 / 全部失败，部分失败汇总为「已提交 M 条，N−M 条未成功」并只对失败项提供重试；后端 400 文案原样透传。
- 相册或相机权限被拒时说明用途并提供「去设置」入口，不反复弹窗。
- 新增依赖 `expo-image-picker`、`expo-image-manipulator`（`npx expo install` 匹配 SDK 57）。

## Capabilities

### New Capabilities

- `native-source-capture`：原生端采集入口、表单、图片预处理、权限处理、multipart 上传通道与超时、批次键与幂等重试、逐张进度、部分失败与重试、提交后触发处理。

### Modified Capabilities

- `native-mobile-foundation`：把「收集栏目在能力接入前显示未接入状态」收敛为只覆盖尚未接入的待处理与知识栏目，并明确收集栏目按其自身能力规格提供采集入口。

## Impact

`mobile/` 新增采集模块（入口、表单、上传通道、图片预处理、权限与结果态）与对应单测，`app/(tabs)/collect.tsx` 由占位替换为采集屏；`mobile/package.json` 新增 `expo-image-picker`、`expo-image-manipulator`、`expo-clipboard` 三个依赖。Web 不改动，不新增端点。

后端随本 change 修一处真机验收发现的既有实现缺陷（不改规格）：处理触发与处理 Worker 的写事务跨越模型调用，导致 SQLite 写锁超时，真机表现为第二次采集「上传失败（HTTP 500）」。修复为触发处理幂等兜底、写库与模型调用分段提交，并给 SQLite 连接启用 WAL 与 15 秒写锁等待；`backend/app/db/session.py` 的改动只在 SQLite 分支生效，生产 MySQL 8 不受影响，回归见 `backend/tests/test_sqlite_concurrency.py`，依据与取舍见 `design.md`。

来源列表、来源详情、改归属、删除与轮询留给后续 change `add-native-source-library`。

## Non-Goals

- 来源列表、筛选、下拉刷新、状态徽标、`done` 副状态与轮询。
- 来源详情、改归属、删除。
- 录音、网页链接采集、系统分享入口、连拍连续扫描、AI 建议徽标、独立「全部来源」页。
- 改变相册访问方式：不申请完整相册读取权限、不自建图库选择界面；Android 14+ 系统选择器交回结果时的系统浮层作为平台已知边界接受（见 `design.md`）。
