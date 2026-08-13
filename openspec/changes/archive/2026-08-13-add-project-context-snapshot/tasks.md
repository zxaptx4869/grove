## 1. 数据模型与迁移

- [x] 1.1 新增 `backend/app/models/project_context.py`，定义 `ProjectContext` 与状态常量，并在 `app/models/__init__.py` 导出
- [x] 1.2 新增 Alembic 迁移创建 `project_contexts`，运行 `cd backend && .venv/bin/alembic upgrade head`

## 2. 生成器抽象与配置

- [x] 2.1 新增 `backend/app/context/` 包：`ProjectContextGenerator` 抽象、`ProjectContextDraft` 与纠正模型、Demo 确定性实现、工厂与未接入桩
- [x] 2.2 在 `Settings` 新增 `context_generator`、`context_refresh_debounce_seconds`、`context_worker_enabled`，更新 `backend/.env.example`

## 3. 上下文服务与 Worker

- [x] 3.1 新增 `backend/app/services/project_context.py`：惰性建行、安排刷新、生成并写回、失败回退、纠正合并与公共上下文组装
- [x] 3.2 新增 `backend/app/context/worker.py`：轮询到期刷新并用条件更新原子认领；在 FastAPI lifespan 启动 Context Worker

## 4. 触发点

- [x] 4.1 在创建项目、更新项目说明、创建/更新/移动/删除/排序目录节点后调用 `schedule_refresh`

## 5. API

- [x] 5.1 新增 `backend/app/api/project_context.py`：查询、纠正、手动重新生成接口，并校验 Project 属于当前 Workspace
- [x] 5.2 在 `backend/app/main.py` 注册项目上下文路由

## 6. 前端展示与纠正

- [x] 6.1 扩展 `frontend/src/lib/api.ts` 与 `frontend/src/lib/queryKeys.ts`，新增项目上下文类型与请求函数
- [x] 6.2 实现 `frontend/src/components/features/ProjectContextPanel.tsx`：展示快照、纠正对话框、重新生成按钮，使用 `useGroveMutation` 显式失效
- [x] 6.3 在项目首页接入 `ProjectContextPanel`

## 7. 测试与验证

- [x] 7.1 后端测试：模型与 Workspace 隔离、初始生成、触发与防抖、失败回退、纠正保留、公共上下文接口、Worker 领取、Provider 边界
- [x] 7.2 前端测试：项目上下文展示、纠正与重新生成触发
- [x] 7.3 运行 `cd backend && .venv/bin/pytest -q && .venv/bin/ruff check .`
- [x] 7.4 运行 `cd frontend && npm test -- --run && npm run lint && npm run build`
- [x] 7.5 运行 `openspec validate --all --strict`
