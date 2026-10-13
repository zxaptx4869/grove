## Why

Web 项目页的「AI 阅读」是知识 Agent 上线前的一次性 Reader 问答入口。知识 Agent 底座（`/api/knowledge-agent`）与全局「知识 Agent」入口（`/agent`）已覆盖同一能力，旧入口只剩并行维护成本：它带来第二套问答界面、第二组 `/api/projects/{id}/reader/*` 端点与第三套 Candidate 保存契约，容易与知识 Agent 的分阶段降级、引用复验口径产生分歧。这条链路在代码里已被显式标注为「兼容边界」，本次整体移除，收敛到统一对话入口。

## What Changes

- **BREAKING**：移除 `POST /api/projects/{project_id}/reader/ask` 与 `POST /api/projects/{project_id}/reader/save-candidate` 两个旧 Reader 端点，及其 API 路由、服务、Agent、Schema 与测试。
- **BREAKING**：Web 项目内导航移除「AI 阅读」入口，`ProjectPage` 不再渲染旧 Reader 视图；`/projects/:id?view=ai-read` 旧链接重定向到该项目首页（`replace`），不再保留该视图。
- 移除 Web 侧 `ReaderView` 组件、`lib/api.ts` 中 Reader 请求与类型、`queryKeys.readerPreview`；`EntryPreviewDialog`（仅被 ReaderView 使用）一并移除。
- 保留知识 Agent 依赖的共享底座：`app/agents/semantic.py`、`app/services/vector_search.py`、`app/services/candidate_creation.py` 不改；其中 `SOURCE_KIND_READER` 常量与「AI 阅读问答」标题映射作为默认值与历史 Source 标题口径保留。
- 同步主规格：`product-shell` 的项目内导航与项目切换视图口径去掉「AI 阅读」；`answer-to-candidate` 收敛为知识 Agent 的共享创建契约。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `product-shell`：项目内导航不再提供「AI 阅读」入口；项目切换保留的视图类型同步去掉「AI 阅读」。
- `answer-to-candidate`：移除仅由旧 Reader 保存入口承载的需求，保留知识 Agent 复用共享 Candidate 创建服务的契约。

## Non-Goals

- 不改动知识 Agent（Conversation / Run / 引用复验 / 候选草稿 / 可观测性）与移动端的任何行为。
- 不删除共享底座模块，也不改 `SOURCE_KIND_READER` 的默认值语义（历史与兜底仍生效）。
- 不动 `docs/prototypes/` 历史原型；不改动现有 6 个活跃 change。
- 不做统一对话入口（`/agent`）本身的改造。

## Impact

- 后端：删除 `backend/app/api/reader.py`、`backend/app/services/reader.py`、`backend/app/agents/reader.py`、`backend/app/schemas/reader.py`、`backend/tests/test_reader.py`，并在 `backend/app/main.py` 摘除路由注册；清理 `backend/tests/test_knowledge_agent_candidate_drafts.py` 共享服务用例中的 reader 字面量。
- Web：`frontend/src/components/layout/AppShell.tsx`、`frontend/src/pages/ProjectPage.tsx`、`frontend/src/components/features/ReaderView.tsx`、`frontend/src/components/features/EntryPreviewDialog.tsx`、`frontend/src/lib/api.ts`、`frontend/src/lib/queryKeys.ts`。
- 文档：`docs/产品蓝图/目录与知识空间.md`（项目内导航清单与「过渡保留」说明）。
- 不影响：移动端、知识 Agent API、正式 Entry / Candidate 数据、Workspace 隔离与 AI 可观测性。实施完成、自动化验证与用户走查通过前不归档、不推送、不合并。
