# 知林 Grove — 代理工作守则（AGENTS.md）

本文件是仓库内 AI 代理（Codex 等）与协作者共同遵守的工作守则，随 OpenSpec 工作流一并维护。

## 1. 产品守则（铁律）

1. **AI 输出永远是候选。** AI 生成的任何抽取、归类、建议、回答，都只能作为候选（Extraction / 建议），不得直接写入或覆盖正式记录（Entry）。
2. **正式记录必须可溯源。** 每条正式 Entry 必须能追溯到其 Source（原始材料）；丢失来源的记录视为缺陷。
3. **数据按 Workspace 隔离。** 用户数据从第一行代码起按 Workspace 隔离，任何跨 Workspace 的读写都是缺陷。
4. **人在环上。** 人的确认/拒绝/修改是产品闭环的一部分，任何自动化不得绕过人的最终决定权。

## 2. 工程工作流（OpenSpec）

- 所有功能变更遵循 OpenSpec 流程：`proposal → specs → design → tasks → 实施 → validate → sync specs → archive → commit`。
- 变更以 change 为单位：先创建 `openspec/changes/<name>/` 并写满四个工件，`openspec validate --all --strict` 通过后再动业务代码。
- 实施完成后执行 `openspec archive <change>` 同步主规格，再提交代码。**归档时机**：归档必须在实施、验证与手动走查全部完成后、最终提交与推送合并之前执行；未归档的 change 不算完成。若因临时安排先推送了代码，必须立即补归档并同步主规格，不允许长期遗留 active change。
- **推送与合并必须经用户确认**：完成实现后先停留在本地分支（可提交、可 push 前待命），用户验证无问题并明确确认后，再推送远端或合并分支。
- **本地提交及时化**：每次完成一段可验证的代码修改（功能、修复、测试、文档或配置）后，立即在本地提交一次，避免改动长期滞留工作区导致丢失或难以回溯；推送与合并仍须经用户确认。
- **分支策略**：开发新功能（OpenSpec change）时，自 proposal 阶段起新建 `codex/<change>` 特性分支，不在 main 上直接开发；小 bug 修复、文档与配置调整不强制新分支。推送与合并前仍须经用户确认。
- **收尾遗留登记**：每次功能变更或任务收尾（归档 / 最终提交前）时，若发现遗留问题或后续优化项，先逐条向用户说明背景、原因与影响，再询问是否需要记录；用户同意后，由代理自行判断适合的分组，将优化项写入 `docs/discussions/Grove后续优化清单.md`，注明来源 change（或任务）与日期，确保后续优化时有据可查。
- CLI 可用命令：`openspec list`、`openspec status --change <name>`、`openspec instructions <artifact> --change <name>`、`openspec validate --all --strict`、`openspec archive <change>`。

## 3. 工程约定

- 技术栈（2026-08-12 锁定）：后端 FastAPI + Pydantic v2 + async SQLAlchemy 2 + Alembic；前端 React 19 + TypeScript + Vite + Tailwind 4 + shadcn/ui + TanStack Query；数据库开发 SQLite、生产 MySQL 8。
- 后端 Python ≥3.12；依赖管理用 backend/pyproject.toml；格式与静态检查用 ruff。
- 环境变量统一走 pydantic-settings，密钥类配置只放占位键，`backend/.env.example` 提供模板，不得提交 `.env`。
- 开发环境后端以 `cd backend && .venv/bin/alembic upgrade head && .venv/bin/uvicorn app.main:app --reload` 启动（`alembic upgrade head` 幂等，已最新时零操作；改代码自动重载）；凡涉及新增或修改 Alembic 迁移的代码改动，`--reload` 不会自动应用迁移，改完必须手动再执行一次 `cd backend && .venv/bin/alembic upgrade head` 再验证；改 `.env` 或安装依赖后仍需手动重启；新增或修改后端端点后先 `curl` 验证（预期 401/200，而非 404）再进入走查；生产环境不使用 `--reload`，生产迁移按变更窗口与回滚策略单独执行。
- Grove Web 是桌面知识整理工作台，从 1024px 视口宽度开始支持完整业务流程；低于该宽度时只显示电脑访问提示，不实现手机 Web 业务界面。
- 提交信息用中文、遵循 Conventional Commits 风格（feat/fix/docs/chore/refactor）。
- 前端服务端状态查询默认即时（TanStack Query `staleTime: 0`，在 `main.tsx` 全局默认）；只有明确静态且昂贵的查询才在各自 `useQuery` 显式设置更长 `staleTime`，并注明缓存理由。后台 Worker 或跨页面变更的数据不得依赖长缓存。
- 产品范围与优先级从 `docs/产品蓝图.md` 路由到对应权威专题；先读索引，再只读取任务相关的 1 至 2 份专题，不默认加载全部产品专题。遇到跨 change 的产品分歧先更新对应专题，具体技术取舍记录到对应 change 的 `design.md`，不要静默猜测。
- **AI 可观测性（防静默降级）**：所有 AI 生成路径必须记录 provider / model / fallback 状态；接口返回成功不等于真实模型调用成功，禁止静默降级。发生降级时必须日志告警，并在响应或界面中可识别。

## 4. 代码注释与沟通语言

- 仓库内代码注释、文档、提交信息一律使用中文。
- 与用户沟通使用中文。
- **术语约定**：用户所说的「旧项目」指 KnowStruct（`/Users/hujun/Documents/软件/trae/KnowStruct`），Grove 的前身产品。
