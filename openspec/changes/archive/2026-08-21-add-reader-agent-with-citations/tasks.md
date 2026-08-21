# add-reader-agent-with-citations 任务清单

## 1. 骨架搭建（Reader Agent 与 schema）

- [x] 1.1 新建 `agents/reader.py`：`ReaderAnswerDraft`（answer / citations / insufficient / conflicts）与 `run_reader_agent`，未配置密钥或模型失败时降级并标记原因
- [x] 1.2 新建 `schemas/reader.py`：问答请求（message / scope / node_id）、回答响应（含 citations / insufficient / conflicts / provider / model / is_fallback / error）、保存请求（question / title / content / citations）

## 2. 后端核心实现

- [x] 2.1 新建 `services/reader.py`：`ask_reader`（加载节点子树或项目 Entry → 复用 `_recall_by_query` 与 `run_semantic_agent` 召回 top-15 → 组装上下文（项目级叠加 Project Context）→ 生成答案 → 应用层校验并丢弃非法引用）
- [x] 2.2 新建 `api/reader.py`：`POST /api/projects/{id}/reader/ask`（节点 / 项目范围，越权 404，Workspace 隔离）
- [x] 2.3 `services/reader.py` 新增 `save_answer_as_candidate`：校验引用（entry / source 属于当前项目与 Workspace）→ 创建「AI 阅读问答」虚拟 Source（text attachment = 回答全文）→ 创建待采纳 Candidate（evidence_refs 引用原始 Source 证据）→ 进入确认台
- [x] 2.4 新建 `POST /api/projects/{id}/reader/save-candidate`（非法 / 越权引用返回 400）
- [x] 2.5 后端测试：新建 `tests/test_reader.py` 覆盖节点 / 项目范围、引用校验、知识不足、模型失败降级、保存转候选、越权隔离；运行 `cd backend && .venv/bin/pytest` 通过

## 3. 前端实现

- [x] 3.1 `lib/api.ts`：新增 ask / save-candidate 接口与类型
- [x] 3.2 `ProjectPage.tsx` 新增「AI 阅读」视图（`?view=ai-read`）与入口
- [x] 3.3 AI 阅读视图组件：消息列表容器（第一版 1 问 1 答）、引用展示与跳转、知识不足 / 冲突提示、「保存为知识」编辑框（先编辑再确认）
- [x] 3.4 前端构建与测试：`cd frontend && npm run build`、`npm run test:run`、改动文件 `npx eslint` 通过（全量 lint 受既有 `DirectoryDraftDialog.tsx` 错误影响，另行清理）

## 4. 验证与收尾

- [x] 4.1 静态检查：`cd backend && .venv/bin/ruff check .` 通过
- [x] 4.2 规格校验：`openspec validate --all --strict` 通过
- [x] 4.3 手工走查：节点 / 项目问答、引用跳转、知识不足提示、保存转候选进确认台
- [x] 4.4 全绿后执行 `openspec archive add-reader-agent-with-citations` 同步主规格，本地提交（不推送、不合并）
