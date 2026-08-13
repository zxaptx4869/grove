## Context

Grove 当前有 Workspace、Project、Node 与基础采集占位（`InboxPage`），但没有 `Source`/`Attachment` 模型，无法承接用户投入的截图与文字。本 change 落地采集基础，让原始材料先「进得来、看得见、可归属」，为后续处理管道（#3）与组织 Agent（#4）提供可溯源的归属对象。

蓝图已锁定：Source 属于 Workspace，可未归属或最多归属一个 Project；附件首批类型为图片/截图与粘贴文字；附件存储初始方案为本地文件系统。

## Goals / Non-Goals

**Goals:**

- 新增 `Source` 与 `Attachment` 模型，按 Workspace 隔离。
- 支持图片批量上传与粘贴图片/文字的采集，采集时可填可选项目与说明。
- 把图片附件落到本地文件系统，数据库只存相对路径，并可通过后端接口访问。
- 提供全局收集箱与项目内「采集与来源」的列表与详情，支持删除。

**Non-Goals:**

- 不引入处理状态机、异步任务、失败重试与幂等。
- 不做 OCR/多模态解析、语义拆分、候选生成。
- 不做 AI 项目推荐、目录推荐与确认台。
- Source 标题本轮只做自动规则，不做 AI 归纳。

## Decisions

### D1：附件存储用本地文件系统，接口层保持可替换

图片附件保存到本地目录（默认 `backend/uploads`），数据库只存相对路径；图片通过后端流式接口访问，不直接作为静态目录暴露。新增配置 `attachment_dir`，目录纳入 `.gitignore`。存储逻辑收敛到 `AttachmentStorage` 服务，后续迁移对象存储时只替换该服务实现。

备选：直接挂载静态目录或存数据库 BLOB。前者会让访问控制绕过 Workspace 校验，后者会让 SQLite 膨胀且不利迁移，故不采用。

### D2：采集走单一 multipart 端点

`POST /api/sources` 使用 `multipart/form-data`，字段：`files[]`（图片，可选）、`text`（文字，可选）、`project_id`（可选）、`note`（可选）。要求 `files` 与 `text` 至少一个且不同时出现：有图片则创建多个 image Attachment，有文字则创建一个 text Attachment。这样图片上传、粘贴图片、粘贴文字复用同一采集语义。

### D3：一次采集的语义

多张图片归为一个 Source，按提交顺序保存为多个 Attachment；一次粘贴归为一个 Source（要么图片、要么文字）。这符合原型中「厨房插座参考（4 张）」与「粘贴内容」的交互。

### D4：Source 标题存储并自动生成，为后续 AI 归纳预留

`Source.title` 作为普通列保存：图片 Source 取第一个图片附件的文件名，文字 Source 取正文首行（截断到合理长度）。本轮不使用 AI；后续 `add-organizing-agent-extraction` 可在解析后覆盖该列，无需新增字段迁移。

### D5：不引入处理状态字段

本 change 不新增 `status` 列。未归属用 `project_id IS NULL` 表达，处理状态机（等待处理/处理中/失败等）由 `add-processing-task-pipeline` 引入。避免底层预留字段被误当成已实现能力。

### D6：删除 Source 做简单级联

删除 Source 时级联删除 Attachment 记录，并删除本地图片文件。由于本阶段 Source 尚未产生 Entry 与证据关系，不做「删除唯一证据保护」，该保护留到 Entry 能力上线后的 change。

### D7：上传校验

图片类型按 MIME/扩展名白名单校验（png、jpg、jpeg、webp）；单文件大小上限 10MB；一次采集最多 5 张图片（多图归一个 Source）。超限返回 400 且不落库，数值以常量固定并覆盖测试。

## Risks / Trade-offs

- [本地文件在删除或迁移时可能残留] → 删除操作在事务提交后再清理文件；记录相对路径便于后续对象存储迁移。
- [图片访问接口若未校验归属可能越权] → 图片访问走 `get_current_workspace`，只允许当前 Workspace 的 Source 附件。
- [一次采集混合图片与文字被误用] → 接口层明确拒绝 `files` 与 `text` 同时出现。
- [标题自动规则对中文长文本不友好] → 文字标题截断到固定长度；AI 归纳标题已在 #4 预留。

## Migration Plan

新增 Alembic 迁移，创建 `sources` 与 `attachments` 两张表：

- `sources(id, workspace_id FK→workspaces, project_id FK→projects NULL, title, note NULL, created_at, updated_at)`
- `attachments(id, source_id FK→sources ON DELETE CASCADE, kind image|text, position, mime_type NULL, file_name NULL, file_path NULL, text_content NULL, created_at)`

开发 SQLite 与生产 MySQL 8 均按现有 `BigInteger().with_variant(Integer, "sqlite")` 约定定义主键与自增。

## Open Questions

- 图片访问本轮返回原图，缓存与缩略图策略留到后续 change。
