## Why

用户整理知识的起点是「把零散材料放进 Grove」。当前仓库只有项目与目录，采集入口是占位空态，没有 `Source`/`Attachment` 模型，无法承接截图、文字等原始证据。这是 P0-A「可信整理闭环」的第一块：先有可溯源、可按 Workspace 隔离的 Source，后续的解析、候选生成与确认台才有归属对象。

## What Changes

- 新增 `source-management` 能力：
  - `Source` 模型：归属 Workspace，可未归属或归属一个 Project，可选采集说明。
  - `Attachment` 模型：图片或文字；一个 Source 可含多张图片或一段文字。
  - 采集：图片批量上传、粘贴图片/文字；采集时可选所属项目与补充说明。
  - 本地附件存储：文件存本地目录，数据库只存相对路径，图片经后端接口访问。
  - Source 列表与详情：全局收集箱（未归属 / 已归属）与项目内「采集与来源」。
  - 删除 Source 时级联删除附件记录与本地文件。
- 前端：实现收集箱（采集框 + 来源列表）与项目内「采集与来源」入口，替换现有占位。

## Capabilities

### New Capabilities

- `source-management`: Source 与 Attachment 模型、图片与文字采集、本地附件存储、项目归属、Source 列表/详情/删除。

### Modified Capabilities

（无）

## Impact

- 后端：新增模型与 Alembic 迁移、采集/列表/详情/删除 API、附件存储服务、配置新增附件目录键、图片访问接口。
- 前端：`InboxPage` 与项目页的「采集与来源」视图、`lib/api` 客户端扩展。
- 配置与仓库：新增本地附件目录（纳入 `.gitignore`），`backend/.env.example` 增加附件目录占位键。
- 无外部服务依赖；本轮不接入 AI 或 OCR。

## Non-Goals

- 不做处理状态机、异步任务、失败重试与幂等（留给 `add-processing-task-pipeline`）。
- 不做 OCR/多模态解析、语义拆分与候选生成（留给 `add-organizing-agent-extraction`）。
- 不做 AI 项目推荐、目录推荐与确认台（留给后续 change）。
- Source 标题本轮使用自动规则（图片取文件名、文字取首行），不做 AI 归纳标题；AI 归纳 Source 标题留给 `add-organizing-agent-extraction`。
- 不做 Entry 证据关系与「删除含唯一证据 Source」的复杂保护（后续 change）。
- 不做移动端采集。
