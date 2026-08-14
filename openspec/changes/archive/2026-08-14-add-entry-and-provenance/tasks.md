## 1. 数据模型与迁移

- [x] 1.1 新增 `backend/app/models/entry.py`，定义 `Entry` 与 `EntrySourceEvidence`，并在 `app/models/__init__.py` 导出
- [x] 1.2 新增 Alembic 迁移创建 `entries` 与 `entry_source_evidences`

## 2. 归档服务

- [x] 2.1 新增 `backend/app/services/entry.py`：归档候选、证据转换、目录校验、编辑与移动
- [x] 2.2 更新候选决策服务，归档后锁定已归档候选

## 3. API

- [x] 3.1 新增 `POST /api/candidates/{id}/archive`
- [x] 3.2 新增 `PATCH /api/entries/{entry_id}` 与 `GET /api/entries/{entry_id}`
- [x] 3.3 注册路由

## 4. 前端确认台归档

- [x] 4.1 候选编辑区增加目录选择器，未选目录禁用采纳
- [x] 4.2 采纳调用归档接口，归档后刷新候选与来源列表

## 5. 知识空间展示

- [x] 5.1 选中目录节点时展示该节点下 Entry 与来源证据入口

## 6. 测试与验证

- [x] 6.1 后端测试：归档原子性、证据转换、目录校验、锁定、编辑移动、Workspace 隔离
- [x] 6.2 前端测试：目录选择、采纳归档、知识空间 Entry 展示
- [x] 6.3 运行 `cd backend && .venv/bin/pytest -q && .venv/bin/ruff check .`
- [x] 6.4 运行 `cd frontend && npm test -- --run && npm run lint && npm run build`
- [x] 6.5 运行 `openspec validate --all --strict`
