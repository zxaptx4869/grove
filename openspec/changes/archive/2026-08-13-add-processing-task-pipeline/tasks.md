## 1. 数据模型与迁移

- [x] 1.1 新增 `backend/app/models/processing.py`，定义 `ProcessingTask`，并在 `app/models/__init__.py` 导出
- [x] 1.2 为 `Source` 增加 `status` 字段，新增 Alembic 迁移，运行 `cd backend && .venv/bin/alembic upgrade head`

## 2. Provider 抽象

- [x] 2.1 新增 `ProcessingProvider` 抽象接口与工厂，Demo 确定性实现，真实 Provider 留桩

## 3. 异步 Worker

- [x] 3.1 在 FastAPI lifespan 启动进程内 asyncio Worker，轮询并原子认领 `等待处理` 任务
- [x] 3.2 实现状态流转（waiting → processing → done / failed）与失败重试、`Source.status` 同步

## 4. API

- [x] 4.1 新增触发处理与重试接口，校验 Source 归属 Workspace
- [x] 4.2 Source 列表与详情返回处理状态

## 5. 前端

- [x] 5.1 来源列表展示处理状态，并对等待处理/失败提供「开始处理 / 重试」按钮
- [x] 5.2 触发后刷新来源列表

## 6. 测试与验证

- [x] 6.1 后端测试：状态机、Worker 领取、失败重试、幂等、Provider 边界
- [x] 6.2 前端测试：状态展示与「开始处理 / 重试」触发
- [x] 6.3 运行 `cd backend && .venv/bin/pytest -q && .venv/bin/ruff check .`
- [x] 6.4 运行 `cd frontend && npm test -- --run && npm run lint && npm run build`
- [x] 6.5 运行 `openspec validate --all --strict`
