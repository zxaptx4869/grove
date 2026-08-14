## 1. Agent 输出与提示词

- [x] 1.1 `ExtractionDraft` 增加 `source_title` 字段，更新提示词与离线样例

## 2. 处理回写

- [x] 2.1 `OrganizingProcessingProvider` 成功后更新 `Source.title`

## 3. 测试与验证

- [x] 3.1 后端测试：文字与图片处理后标题更新、失败保留原标题、离线确定性
- [x] 3.2 运行 `cd backend && .venv/bin/pytest -q && .venv/bin/ruff check .`
- [x] 3.3 运行 `cd frontend && npm test -- --run && npm run lint && npm run build`
- [x] 3.4 运行 `openspec validate --all --strict`
