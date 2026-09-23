## Why

移动端「收集」模块要求弱网下可安全重试上传：当前 `POST /api/sources` 每次调用都会新建 Source，客户端超时后重试（第一次实际已成功）会留下重复来源与重复附件，用户无法判断哪条是真实的。移动端还需要在「每张一条」时给出更可读的标题，并在列表里展示失败原因与重试次数；后者数据已在 `ProcessingTask.error` / `retry_count`，但没有出现在 `SourceOut` 中，移动端只能看到 `failed` 状态却看不到原因。

采集合同缺口不补齐，移动端无法开工，Web 端弱网重试也继续产生重复来源。因此本 change 先只做**后端采集合同扩展 + Web 端接入**，把幂等、标题覆盖与失败信息三项合同固定下来。

## What Changes

- `Source` 增加可选 `capture_key`（长度上限 128），在同一 Workspace 内唯一；`POST /api/sources` 接受可选 multipart 字段 `capture_key`：同键已存在时直接返回已存在 Source（200），不新建、不写附件、不落盘；未命中按现有流程创建（201）。并发同键由唯一约束兜底，冲突后回查已存在记录并清理本次已落盘文件。幂等命中检查先于落盘。
- `POST /api/sources` 增加可选 `title`：传入非空白值时用它（strip 后截断 255），未传/空白保持现有默认（图片取第一个文件名、文字取正文首行）。
- `SourceOut` 增加 `failure_reason` 与 `retry_count`：仅当任务 `failed` 且存在 `error` 时给出文案，其它状态为 `null`；重试次数取任务实际值，无任务为 0；所有返回 `SourceOut` 的路径口径一致，任务信息批量读取，列表不产生 N+1。
- Web 端 `SourceCapture` 提交时携带 `capture_key`：同一次采集动作的连续重试复用同一个键，成功后清空；`POST /api/sources/{id}/process` 的幂等语义经核实不破坏状态，Web 端不新增判断。
- 新增一次 Alembic 迁移（新增列 + `(workspace_id, capture_key)` 唯一索引），SQLite 与 MySQL 8 都可执行。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `source-management`：新增采集幂等键、采集标题覆盖与 `SourceOut` 失败信息三项合同；标题生成需求补充客户端覆盖入口。
- `processing-task`：幂等与不覆盖要求补充「重复触发已有任务不得破坏状态」，覆盖幂等采集命中后再次触发处理的路径。

## Impact

后端 `Source` 模型与 Alembic 迁移、`POST /api/sources` 请求参数、`SourceOut` 响应字段、`backend/app/api/sources.py` 各返回路径的任务信息批量读取；Web 端 `frontend/src/components/features/SourceCapture.tsx` 的提交参数。字段均为新增或可选，旧客户端与既有数据不受影响。

## Non-Goals

- 移动端界面、上传通道、图片压缩与权限处理（属于后续 change）。
- 独立「失败原因」端点、`GET /api/sources` 条数上限/分页/筛选行为调整、Web 界面新增失败原因展示。
- 批次分组展示、批量操作、`capture_key` 前缀聚合。
