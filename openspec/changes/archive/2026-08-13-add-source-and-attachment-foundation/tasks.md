## 1. 数据模型与迁移

- [x] 1.1 在 `backend/app/models/` 新增 `source.py`，定义 `Source` 与 `Attachment`，并在 `app/models/__init__.py` 导出
- [x] 1.2 新增 Alembic 迁移创建 `sources` 与 `attachments`，运行 `cd backend && .venv/bin/alembic upgrade head`

## 2. 附件存储服务

- [x] 2.1 新增 `backend/app/services/attachment_storage.py`，实现图片保存、删除与路径解析
- [x] 2.2 在 `Settings` 新增 `attachment_dir`，更新 `backend/.env.example`，并将上传目录纳入 `.gitignore`

## 3. API 实现

- [x] 3.1 新增 `backend/app/api/sources.py`：POST 采集、GET 列表、GET 详情、PATCH 归属/说明、DELETE
- [x] 3.2 新增图片访问接口，校验附件属于当前 Workspace
- [x] 3.3 在 `backend/app/main.py` 注册 sources 路由

## 4. 前端采集与列表

- [x] 4.1 扩展 `frontend/src/lib/api.ts` 的 Source/Attachment 类型与请求函数
- [x] 4.2 实现 `frontend/src/pages/InboxPage.tsx` 采集框与来源列表
- [x] 4.3 在项目页实现「采集与来源」视图，列表按当前项目过滤

## 5. 测试与验证

- [x] 5.1 新增后端测试：模型、采集、列表/详情、归属、删除、Workspace 隔离
- [x] 5.2 新增前端测试：收集箱采集与来源列表、项目内来源过滤
- [x] 5.3 运行 `cd backend && .venv/bin/pytest -q && .venv/bin/ruff check .`
- [x] 5.4 运行 `cd frontend && npm test -- --run && npm run lint && npm run build`
- [x] 5.5 运行 `openspec validate --all --strict`
