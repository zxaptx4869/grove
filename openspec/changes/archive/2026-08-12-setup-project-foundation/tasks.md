## 1. 工作流与仓库骨架

- [x] 1.1 在 `codex/init-scaffold` 分支工作，补全根目录 `AGENTS.md`（产品铁律 + OpenSpec 工作流 + 工程约定）
- [x] 1.2 配置 `openspec/config.yaml`（spec-driven schema、项目上下文、工件规则）
- [x] 1.3 编写 `docs/项目上下文与文档路由.md` 并登记主要文档
- [x] 1.4 完善根目录 `.gitignore`（.env、缓存、构建产物、数据库文件）
- [x] 1.5 运行 `openspec validate --all --strict` 确认工作流骨架校验通过

## 2. 后端骨架（backend/）

- [x] 2.1 创建 `backend/pyproject.toml`（FastAPI、pydantic-settings、async SQLAlchemy 2、alembic、aiosqlite、pytest、ruff；Python ≥3.12）
- [x] 2.2 实现 `app/core/config.py`（pydantic-settings：DATABASE_URL 默认 SQLite、FRONTEND_ORIGINS、AI 相关占位键）
- [x] 2.3 实现 `app/db/session.py`（async engine、async_sessionmaker、Base）与 FastAPI 会话依赖
- [x] 2.4 实现 `app/main.py` 应用工厂：CORS、`/healthz`、挂载 API 路由
- [x] 2.5 配置 Alembic（env.py 读 Settings.DATABASE_URL），生成空初始迁移并注释 SQLite/MySQL 8 方言差异
- [x] 2.6 编写 `backend/.env.example` 与最小 pytest 用例（健康检查 + 配置覆盖）
- [x] 2.7 运行 `pytest -q`、`ruff check .`、`alembic upgrade head` 验证后端全绿

## 3. AI 层骨架（backend/app/ai/）

- [x] 3.1 定义 `AIProvider` 抽象基类与 `AICandidate` 候选结果模型（is_candidate 铁律）
- [x] 3.2 实现 `DemoProvider`（确定性输出，无网络依赖）
- [x] 3.3 实现 `get_ai_provider` 工厂：demo 生效，deepseek/doubao 占位并明确「未接入」
- [x] 3.4 为 AI 层补充 pytest 用例并通过

## 4. 前端骨架（frontend/）

- [x] 4.1 用 Vite 初始化 React 19 + TypeScript 工程，安装 Tailwind 4、shadcn/ui、React Router、TanStack Query
- [x] 4.2 配置 Tailwind 4 与 shadcn/ui 基础（button、utils），配置 `VITE_API_BASE_URL`
- [x] 4.3 实现 `main.tsx` / `App.tsx`：Router + QueryClientProvider + 全局布局（390px 可用）
- [x] 4.4 实现占位首页 `/` 与健康检查页 `/health`（TanStack Query 调 `/healthz`）
- [x] 4.5 配置 vitest + @testing-library/react 最小用例，配置 eslint + prettier
- [x] 4.6 运行 `npm test -- --run`、`npm run lint`、`npm run build` 验证前端全绿

## 5. 最小链路与收尾

- [x] 5.1 启动前后端，验证 `/healthz` 返回 200、健康检查页展示正常
- [x] 5.2 更新 README.md（启动方式、测试/lint/build 命令）
- [x] 5.3 运行 `openspec validate --all --strict` 全量校验
- [x] 5.4 `openspec archive setup-project-foundation` 同步主规格
- [x] 5.5 按「骨架文档 → 后端 → 前端 → 收尾」分提交，推送 `codex/init-scaffold` 到远端
