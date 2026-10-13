## 1. 工件与前置校验

- [x] 1.1 建立 `codex/remove-web-ai-reader` 特性分支并 `openspec new change remove-web-ai-reader`。
- [x] 1.2 写 proposal / specs / design / tasks，`openspec validate --all --strict` 通过后再动业务代码。验收：四类工件齐备，`openspec validate --all --strict` 68 项 0 失败。

## 2. 后端移除旧 Reader 链路

- [x] 2.1 删除 `backend/app/api/reader.py`、`backend/app/services/reader.py`、`backend/app/agents/reader.py`、`backend/app/schemas/reader.py`、`backend/tests/test_reader.py`。
- [x] 2.2 `backend/app/main.py` 摘除 `reader_router` 的 import 与 `app.include_router(reader_router)`。
- [x] 2.3 确认保留共享底座：`backend/app/agents/semantic.py`、`backend/app/services/vector_search.py`、`backend/app/services/candidate_creation.py`（含 `SOURCE_KIND_READER` 常量与 `_SOURCE_TITLE_PREFIX` 的 reader 映射）。验收：`rg -n "reader" backend/app` 仅剩 `candidate_creation.py` 的共享常量与映射，其余为 sqlite 局部变量。顺手清理 `knowledge_agent/candidate.py` 与 `candidate_creation.py` 中指向旧 Reader 的注释。
- [x] 2.4 清理 `backend/tests/test_knowledge_agent_candidate_drafts.py` 共享服务回滚用例（`test_shared_creation_rolls_back_on_transaction_failure`）中的 `provider="reader"` / `model="reader"` 字面量，用例保留并改为知识 Agent 语境（`provider="knowledge_agent"`、`model="draft_confirmed"`、显式 `source_kind=SOURCE_KIND_KNOWLEDGE_AGENT`）。
- [x] 2.5 验收：`cd backend && .venv/bin/ruff check .` 通过；`.venv/bin/pytest -q` 仅 `tests/test_embedding_retrieval.py::test_backfill_creates_missing_rows` 失败（既有基线噪声，单跑通过），`test_knowledge_agent_candidate_drafts.py` 全绿。

## 3. Web 移除 AI 阅读

- [x] 3.1 删除 `frontend/src/components/features/ReaderView.tsx` 与 `frontend/src/components/features/EntryPreviewDialog.tsx`。
- [x] 3.2 `frontend/src/lib/api.ts` 移除 `Reader*` 类型与 `askReader` / `saveReaderAnswer`；`frontend/src/lib/queryKeys.ts` 移除 `readerPreview`。
- [x] 3.3 `frontend/src/components/layout/AppShell.tsx` 移除「AI 阅读」导航项与 `isAiRead` 判定（含未再使用的 `BookOpen` 图标导入），`isHome` 判定同步更新。
- [x] 3.4 `frontend/src/pages/ProjectPage.tsx` 移除 `isAiReadView` 分支、标题/描述与 `ReaderView` 渲染，并对 `?view=ai-read` 做 `<Navigate replace>` 重定向到该项目的项目首页。
- [x] 3.5 验收：`npm run typecheck` 通过；`npm run lint` 仅剩 `DirectoryDraftDialog.tsx` 2 条既有 warning；`npm run test:run` 33 文件 188 用例全绿；`rg -n "Reader|ai-read|readerPreview" frontend/src` 仅剩重定向判断。

## 4. 文档同步

- [x] 4.1 `docs/产品蓝图/目录与知识空间.md`：项目层导航清单移除「AI 阅读」条目，并把「现有项目页入口可在统一对话入口接入前作为过渡保留」改为已收敛到统一「知识 Agent」入口；同时去掉「知识全景与知识空间目录浏览、AI 阅读平级」中的过期引用。
- [x] 4.2 `docs/prototypes/` 保持不动（历史原型，不代表当前能力）。

## 5. 验证与走查

- [x] 5.1 全量命令：`cd backend && .venv/bin/ruff check . && .venv/bin/pytest -q`（仅既有基线噪声失败）、`cd frontend && npm run typecheck && npm run lint && npm run test:run`（188 用例全绿）。
- [x] 5.2 后端冒烟：未重启服务，沿用运行中的开发后端（`--reload` 已加载新代码）实测：旧端点 `POST /api/projects/1/reader/ask`、`/reader/save-candidate` 均返回 404，`GET /api/knowledge-agent/conversations` 返回 401；另经 `app.openapi()` 核对 reader 路由为 0 条、知识 Agent 路由 18 条。
- [x] 5.3 `openspec validate --all --strict` 收尾再执行一次并记录结果：68 项 0 失败。
- [x] 5.4 提供 Web 走查清单交用户验收：项目内导航无「AI 阅读」、`?view=ai-read` 重定向到项目首页、知识空间 / 确认台 / 知识 Agent / 移动端不受影响。验收记录（2026-10-13）：用户反馈可见改动只有导航项消失、无其他可走查项，并据此批准归档；Agent 未受影响由 diff 与 `test_knowledge_agent_*` 全绿佐证。

## 6. 收尾

- [x] 6.1 每完成一段可验证修改（工件、后端、Web、文档）即做本地阶段提交。
- [x] 6.2 归档前逐条比对主规格 `product-shell` 与 `answer-to-candidate`。归档结果：`answer-to-candidate` 由 7 条需求收敛为 2 条（+1/-6），`product-shell` 两处 MODIFIED；`answer-to-candidate` 的 Purpose 已同步为知识 Agent 口径。
- [x] 6.3 归档、推送与合并须用户明确批准。记录（2026-10-13）：用户批准并按 `openspec archive remove-web-ai-reader -y` 归档为 `2026-10-13-remove-web-ai-reader`；推送与合并尚未批准。
