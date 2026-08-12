## Why

Grove 仓库目前只有产品提案与初始化提示词，没有可运行的工程骨架与开发流程。不先搭好骨架，后续所有功能切片都会缺乏统一的后端/前端/AI 接入方式与验证手段。本次 change 建立工程与流程地基，让下一个业务 change（如登录）能在稳定、可测试的骨架上展开。

## What Changes

- 建立 OpenSpec 工作流骨架：`AGENTS.md`（产品守则 + 工作流约定）、`openspec/config.yaml`（项目上下文与工件规则）、`docs/项目上下文与文档路由.md`（文档入口）。
- 初始化后端工程 `backend/`：FastAPI 应用工厂、pydantic-settings 配置、CORS、健康检查 `/healthz`、async SQLAlchemy 2 引擎与会话、Alembic 初始迁移（开发 SQLite / 生产 MySQL 8）、pytest 最小用例、ruff 配置。
- 初始化前端工程 `frontend/`：Vite + React 19 + TypeScript + Tailwind 4 + shadcn/ui 基础、React Router、TanStack Query、健康检查页与占位首页、vitest 最小用例、eslint/prettier 配置，保证 390px 移动宽度可用。
- 建立 AI 层骨架：`AIProvider` 抽象接口 + `DemoProvider`（确定性实现）+ `get_ai_provider` 工厂（可切换 deepseek / doubao / demo，仅定义，不接真实 API）。
- 打通最小可运行链路：前后端可启动、`/healthz` 返回 200、测试/lint/build 全绿、OpenSpec validate 通过。
- Git 工作流：在 `codex/init-scaffold` 分支开发，完成后提交并推送远端。

## Capabilities

### New Capabilities

- `project-workflow`: 仓库级开发流程骨架——AGENTS.md 产品守则、OpenSpec 配置与文档路由，保证后续 change 有统一入口与校验方式。
- `backend-foundation`: 后端工程骨架——应用工厂、配置、健康检查、数据库引擎/会话、迁移、测试与静态检查。
- `frontend-foundation`: 前端工程骨架——构建链、样式体系、路由、数据获取、健康检查页、测试/lint/build。
- `ai-provider`: AI 接入抽象——Provider 接口、确定性 Demo 实现与工厂切换，为后续真实 AI 接入预留稳定边界。

### Modified Capabilities

- 无（当前没有既有规格）。

## Impact

- 新增目录：`backend/`、`frontend/`、`openspec/`（changes/ 与 specs/）、`docs/` 扩展。
- 新增文件：`AGENTS.md`、`openspec/config.yaml`、后端应用/迁移/测试、前端应用/配置/测试。
- 新增依赖：后端 FastAPI、pydantic v2、SQLAlchemy 2、alembic、aiosqlite、pytest、ruff 等；前端 React 19、Vite、Tailwind 4、shadcn/ui、TanStack Query、vitest 等。
- 不引入业务数据模型（User/Workspace/Entry 等）、不接真实 AI/OCR API、不实现登录与业务功能。
