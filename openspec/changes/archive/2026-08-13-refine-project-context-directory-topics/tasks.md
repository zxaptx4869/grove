## 1. 生成器修正

- [x] 1.1 `DemoProjectContextGenerator.generate` 的 `directory_topics` 只取顶级目录节点

## 2. 前端折叠展示

- [x] 2.1 `ProjectContextPanel` 增加目录主题展示上限与剩余数量提示

## 3. 测试与验证

- [x] 3.1 修正后端生成测试，断言目录主题为顶级节点
- [x] 3.2 补充前端目录主题折叠测试
- [x] 3.3 运行 `cd backend && .venv/bin/pytest -q && .venv/bin/ruff check .`
- [x] 3.4 运行 `cd frontend && npm test -- --run && npm run lint && npm run build`
- [x] 3.5 运行 `openspec validate --all --strict`
