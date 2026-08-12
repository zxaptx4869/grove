# 知林 Grove

个人知识管家：把散落在各处的经验与知识（收藏、截图、文档、链接），在人与 AI 的共创下，沉淀为属于你自己的结构化知识库；并逐步具备回忆与主动发现的能力。

## 文档入口

- 产品提案：[PROPOSAL.md](PROPOSAL.md)
- 项目上下文与文档路由：[docs/项目上下文与文档路由.md](docs/项目上下文与文档路由.md)
- 代理工作守则：[AGENTS.md](AGENTS.md)
- OpenSpec 工作流：[openspec/](openspec/)

## 目录结构

```text
grove/
├── AGENTS.md          # 代理工作守则（产品铁律 + 工程约定）
├── PROPOSAL.md        # 产品提案与技术选型
├── docs/              # 项目文档
├── openspec/          # OpenSpec 工作流（changes/ 与 specs/）
├── backend/           # FastAPI 后端（Python ≥3.12）
└── frontend/          # React 19 + Vite 前端
```

## 本地开发

### 后端

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
# 可选：MySQL 8 驱动
.venv/bin/pip install -e ".[mysql]"

# 配置环境变量（模板见 backend/.env.example）
cp .env.example .env

# 启动（默认 http://127.0.0.1:8000）
.venv/bin/uvicorn app.main:app --reload

# 数据库迁移（默认 SQLite；生产通过 DATABASE_URL 切换 MySQL 8）
.venv/bin/alembic upgrade head
```

验证：`GET http://127.0.0.1:8000/healthz` 返回 200。

### 前端

```bash
cd frontend
npm install

# 配置环境变量（模板见 frontend/.env.example，可省略）
cp .env.example .env

# 启动（http://localhost:5173，/healthz 代理到本地后端）
npm run dev
```

访问 `http://localhost:5173/health` 查看后端健康状态。

## 质量检查

```bash
# 后端：测试 + lint
cd backend && .venv/bin/pytest -q && .venv/bin/ruff check .

# 前端：测试 + lint + build
cd frontend && npm test -- --run && npm run lint && npm run build

# OpenSpec：全量校验（变更提案与主规格）
openspec validate --all --strict
```

## OpenSpec 工作流

所有功能变更遵循 OpenSpec 流程：`proposal → specs → design → tasks → 实施 → validate → sync specs → archive → commit`。详见 [AGENTS.md](AGENTS.md)。
