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
- 实施完成后执行 `openspec archive <change>` 同步主规格，再提交代码。
- **推送与合并必须经用户确认**：完成实现后先停留在本地分支（可提交、可 push 前待命），用户验证无问题并明确确认后，再推送远端或合并分支。
- **本地提交及时化**：每次完成一段可验证的代码修改（功能、修复、测试、文档或配置）后，立即在本地提交一次，避免改动长期滞留工作区导致丢失或难以回溯；推送与合并仍须经用户确认。
- CLI 可用命令：`openspec list`、`openspec status --change <name>`、`openspec instructions <artifact> --change <name>`、`openspec validate --all --strict`、`openspec archive <change>`。

## 3. 工程约定

- 技术栈（2026-08-12 锁定）：后端 FastAPI + Pydantic v2 + async SQLAlchemy 2 + Alembic；前端 React 19 + TypeScript + Vite + Tailwind 4 + shadcn/ui + TanStack Query；数据库开发 SQLite、生产 MySQL 8。
- 后端 Python ≥3.12；依赖管理用 backend/pyproject.toml；格式与静态检查用 ruff。
- 环境变量统一走 pydantic-settings，密钥类配置只放占位键，`backend/.env.example` 提供模板，不得提交 `.env`。
- Grove Web 是桌面知识整理工作台，从 1024px 视口宽度开始支持完整业务流程；低于该宽度时只显示电脑访问提示，不实现手机 Web 业务界面。
- 提交信息用中文、遵循 Conventional Commits 风格（feat/fix/docs/chore/refactor）。
- 前端服务端状态查询默认即时（TanStack Query `staleTime: 0`，在 `main.tsx` 全局默认）；只有明确静态且昂贵的查询才在各自 `useQuery` 显式设置更长 `staleTime`，并注明缓存理由。后台 Worker 或跨页面变更的数据不得依赖长缓存。
- 产品范围与优先级从 `docs/产品蓝图.md` 路由到对应权威专题；先读索引，再只读取任务相关的 1 至 2 份专题，不默认加载全部产品专题。遇到跨 change 的产品分歧先更新对应专题，具体技术取舍记录到对应 change 的 `design.md`，不要静默猜测。

## 4. 代码注释与沟通语言

- 仓库内代码注释、文档、提交信息一律使用中文。
- 与用户沟通使用中文。
