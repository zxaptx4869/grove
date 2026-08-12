## Context

Grove 仓库目前只有产品提案（PROPOSAL.md）与初始化提示词，尚无任何可运行代码。本次 change 的目标是搭建工程与流程骨架：OpenSpec 工作流、后端、前端、AI 抽象，打通「启动 → 健康检查 → 测试/lint/build → 提交推送」的最小链路。后续业务 change（登录、采集、抽取、确认、归档）将在本骨架上展开，因此骨架决策需要可追溯、可扩展，且不引入业务逻辑。

约束条件：

- 技术栈已在 PROPOSAL.md 第 9、13 节锁定，不得偏离。
- 开发数据库 SQLite、生产 MySQL 8，迁移必须在两库可跑并标注差异。
- 前端保证 390px 移动宽度可用。
- 全程中文注释与文档；遵循 OpenSpec 顺序（proposal → specs → design → tasks → 实施 → validate → sync → archive → commit）。

## Goals / Non-Goals

**Goals:**

- 建立可验证的 OpenSpec 工作流骨架与产品守则（AGENTS.md）。
- 后端：应用工厂、配置、CORS、`/healthz`、async SQLAlchemy、Alembic 迁移骨架、pytest + ruff 全绿。
- 前端：Vite + React 19 + TS、Tailwind 4 + shadcn/ui、React Router、TanStack Query、健康检查页、vitest + eslint + build 全绿。
- AI 层：Provider 抽象 + Demo 确定性实现 + 工厂切换，不接真实 API。
- 在 `codex/init-scaffold` 分支完成，提交并推送。

**Non-Goals:**

- 登录/认证、采集、抽取、确认、搜索等业务功能（第一个功能切片另开 change）。
- 真实 AI / OCR 接入（deepseek/doubao 仅定义不接线）。
- CopilotKit、pydantic-ai 代码接入（仅保留文档决策）。
- 移动端、部署、OSS 接入。
- 业务数据模型（User/Workspace/Entry 等）与业务迁移。

## Decisions

### D1：仓库结构与文档路由

根目录放 `AGENTS.md`、`PROPOSAL.md`、`README.md`、`docs/`、`openspec/`、`backend/`、`frontend/`。`docs/项目上下文与文档路由.md` 作为文档入口，登记所有文档路径与用途。

**理由**：单仓、目录即心智；新协作者先读文档路由再进代码。

### D2：后端应用工厂与配置

- `backend/app/main.py` 暴露 `create_app()` 应用工厂，`main:app` 为 ASGI 入口。
- `backend/app/core/config.py` 用 pydantic-settings 定义 `Settings`：`DATABASE_URL` 默认 `sqlite+aiosqlite:///./grove.db`、`FRONTEND_ORIGINS` 默认含 `http://localhost:5173` 与 `http://127.0.0.1:5173`、`AI_PROVIDER` 默认 `demo`，AI/认证键位留占位。
- `.env` 支持：后端加载 `backend/.env`，模板见 `backend/.env.example`。

**备选**：Django/Flask —— 技术栈已锁定 FastAPI，不做比较。Settings 单例 vs 每次实例化：单例缓存更简单，测试中可通过环境变量在进程启动前注入。

### D3：健康检查

`GET /healthz` 返回 200 + `{"status": "ok"}`。不依赖数据库连通性，避免「骨架阶段无迁移也起不来」。

**备选**：健康检查含 DB ping —— 更严格但会让 lint/测试环境必须先迁移；骨架阶段选简单形式，业务 change 再升级为 readiness。

### D4：异步数据库基础设施

- `backend/app/db/session.py`：async engine（SQLAlchemy 2 `create_async_engine`）、`async_sessionmaker`、`Base(DeclarativeBase)`。
- FastAPI 依赖 `get_db_session` 供后续业务 change 使用；本 change 只建空迁移（无业务表），验证机制可用。

**备选**：同步 SQLAlchemy —— 与提案锁定的 async 不符。引擎/会话集中在一处，避免每个路由自行创建。

### D5：Alembic 迁移骨架与双库策略

- `alembic.ini` + `alembic/env.py` 从 `Settings.DATABASE_URL` 读取连接串。
- 初始迁移为**空迁移**（仅创建 `alembic_version`），在迁移文件注释中标注 SQLite / MySQL 8 方言差异（主键自增、Text 长度、URL 参数等）。
- 业务表迁移在后续 change 中追加；双库兼容靠「通用类型 + 方言注意项注释」约定。

**备选**：初始迁移直接建业务表 —— 违反 Non-Goals，业务模型未定。空迁移让两库都能 `alembic upgrade head` 验证管道。

### D6：AI Provider 抽象

- `backend/app/ai/base.py`：`AIProvider` 抽象基类，定义 `async def complete(messages, **kwargs) -> AICandidate`。
- `AICandidate`（Pydantic v2）：`content`、`is_candidate=True`、`provider`、`model` 等字段，承载「输出永远是候选」铁律。
- `backend/app/ai/demo.py`：`DemoProvider` 确定性输出（拼接输入 + 固定文案），无网络依赖。
- `backend/app/ai/factory.py`：`get_ai_provider(settings)` 按 `AI_PROVIDER` 返回 `demo`；`deepseek`/`doubao` 类只定义占位，构造或调用时抛出「未接入」的明确错误。

**备选**：直接接真实 SDK —— 超出骨架范围；统一抽象保证后续换供应商不改消费方。

### D7：前端工程布局

- Vite + React 19 + TS；`frontend/src/main.tsx` 入口，`App.tsx` 组装 Router + QueryClientProvider。
- Tailwind 4（`@tailwindcss/vite` 插件 + CSS `@import "tailwindcss"`），shadcn/ui 用 CLI 初始化基础组件（button、utils）。
- 页面：`/` 占位首页、`/health` 健康检查页（TanStack Query 调 `/healthz`，地址来自 `VITE_API_BASE_URL`，默认 `http://localhost:8000`）。
- 390px 兼容：容器用流式布局 + `max-w`，验收时在 390px 视口检查无横向滚动。

**备选**：不用 shadcn/ui —— 技术栈已锁定；只用基础组件，避免引入用不到的系统。

### D8：测试与工具链

- 后端：pytest（`app/tests/` 放最小用例）+ ruff（pyproject.toml 配置 line-length=100、目标 Python 3.12）。
- 前端：vitest + @testing-library/react + jsdom 最小用例；eslint（typescript-eslint + react-hooks + react-refresh）+ prettier。
- 依赖管理：后端 `pyproject.toml`；前端 `package.json` + lockfile。

### D9：Git 分支与提交

开发在 `codex/init-scaffold` 分支进行；按「骨架文档 → 后端 → 前端 → 验证 → 归档」分提交，最后推送远端。

## Risks / Trade-offs

- [SQLite 与 MySQL 8 方言差异] → 空迁移起步 + 后续迁移强制使用通用类型并在文件头注释方言差异；CI 中至少跑通 SQLite，MySQL 路径留部署前验证。
- [Python 3.14（本机）与锁定 3.12 的最低版本差异] → `requires-python = ">=3.12"`，代码避免 3.14 专属语法，本地以 3.14 验证通过即可。
- [Tailwind 4 与 shadcn/ui 初始化兼容性] → 使用当前版本 CLI 与 `@tailwindcss/vite` 插件；若 CLI 生成配置冲突，以 Tailwind 4 官方方式为准并记录。
- [空迁移被误解为「没做数据库」] → 迁移文件与 README 明确注释：机制可用，业务表由后续 change 追加。
- [CORS 配置过宽导致安全隐患] → 默认只允许本地开发源，生产来源通过环境变量显式配置。

## Migration Plan

1. 在 `codex/init-scaffold` 分支按上述决策实施骨架。
2. 后端：`pytest -q` + `ruff check .` 全绿；前端：`npm test -- --run` + `npm run lint` + `npm run build` 全绿。
3. `openspec validate --all --strict` 通过后 `openspec archive setup-project-foundation` 同步主规格。
4. 提交并推送。回滚策略：骨架提交可整体 revert；无数据迁移风险（空迁移）。

## Open Questions

- 无阻塞项。部署方式、真实 AI 供应商、业务表结构均按提案留给后续 change 决策。
