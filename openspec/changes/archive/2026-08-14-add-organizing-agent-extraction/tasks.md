## 1. 数据模型与迁移

- [x] 1.1 新增 `backend/app/models/extraction.py`，定义 `Extraction` 与 `Candidate`，并在 `app/models/__init__.py` 导出
- [x] 1.2 新增 Alembic 迁移创建 `extractions` 与 `candidates`，运行 `cd backend && .venv/bin/alembic upgrade head`

## 2. Organizing Agent 结构化输出

- [x] 2.1 新增 `backend/app/agents/organizing.py`，定义 `CandidateDraft`、`EvidenceRef`、`ExtractionDraft` 与 Agent
- [x] 2.2 实现文字上下文组装与图片 OCR 文本组装，保持附件 ID 追踪

## 3. 处理 Provider 接入

- [x] 3.1 实现 `OrganizingProcessingProvider`，生成并持久化 Extraction/Candidate
- [x] 3.2 实现版本化幂等：成功取代旧 active，失败保留旧 active
- [x] 3.3 更新 `ProcessingProvider` 工厂默认实现

## 4. Candidate 查询 API

- [x] 4.1 新增 `backend/app/api/candidates.py`：`GET /api/sources/{source_id}/candidates`
- [x] 4.2 在 `backend/app/main.py` 注册候选路由

## 5. 前端最小预览

- [x] 5.1 扩展 `frontend/src/lib/api.ts` 与 `queryKeys.ts`
- [x] 5.2 在来源详情/列表提供只读候选预览，标注 AI 候选

## 6. 测试与验证

- [x] 6.1 后端测试：结构化输出、证据引用、版本化幂等、失败回退、Workspace 隔离
- [x] 6.2 前端测试：候选预览与 AI 候选文案
- [x] 6.3 运行 `cd backend && .venv/bin/pytest -q && .venv/bin/ruff check .`
- [x] 6.4 运行 `cd frontend && npm test -- --run && npm run lint && npm run build`
- [x] 6.5 运行 `openspec validate --all --strict`
