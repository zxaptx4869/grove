## 1. 依赖与配置底座

- [x] 1.1 在 `backend/pyproject.toml` 增加 `pydantic-ai-slim[openai]` 与 `keyring`
- [x] 1.2 更新 `Settings` 与 `backend/.env.example`，移除运行时密钥占位，保留 Provider/模型默认值

## 2. 密钥存储

- [x] 2.1 新增 `SecretStore` 抽象与系统钥匙串实现，测试用内存实现
- [x] 2.2 新增 `ai_provider_settings` 模型与 Alembic 迁移

## 3. 模型服务层与 Provider

- [x] 3.1 新增文本/视觉模型服务层，按 Workspace 配置返回 PydanticAI Model 或离线测试模型
- [x] 3.2 接入 DeepSeek 文本 Provider 与豆包视觉 Provider
- [x] 3.3 移除旧 `backend/app/ai/` 手写骨架并迁移相关测试

## 4. 模型设置 API

- [x] 4.1 新增脱敏查询、保存、清除、测试连接接口，校验 Workspace 归属
- [x] 4.2 在 `backend/app/main.py` 注册模型设置路由

## 5. 前端模型设置

- [x] 5.1 扩展 `frontend/src/lib/api.ts` 与 `queryKeys.ts`
- [x] 5.2 新增模型设置入口与页面，支持配置文本/视觉密钥、展示脱敏状态、测试连接

## 6. 测试与验证

- [x] 6.1 后端测试：密钥存储不落明文、Workspace 隔离、脱敏返回、离线回退、测试连接状态流转、Provider 缺密钥报错
- [x] 6.2 前端测试：模型设置展示、保存与测试连接触发
- [x] 6.3 运行 `cd backend && .venv/bin/pytest -q && .venv/bin/ruff check .`
- [x] 6.4 运行 `cd frontend && npm test -- --run && npm run lint && npm run build`
- [x] 6.5 运行 `openspec validate --all --strict`
