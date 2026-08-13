# 知林 Grove

面向个人项目的 AI 知识共创工具：把散落在截图、文字、网页和文档中的信息，整理成可确认、可追溯、符合个人理解方式的知识库，并逐步帮助用户发现知识缺口。

## 文档入口

README 是仓库的唯一文档导航入口：

| 文档 | 用途 |
|---|---|
| [产品蓝图与功能优先级](docs/产品蓝图与功能优先级.md) | 当前产品定义、核心对象、Agent 边界、技术基线、功能优先级和 change 顺序 |
| [代理工作守则](AGENTS.md) | 产品铁律、OpenSpec 流程、工程规范和沟通约定 |
| [OpenSpec 主规格](openspec/specs/) | 已归档能力的当前可验证行为 |
| [OpenSpec 活动变更](openspec/changes/) | 正在规划或实施的 proposal、specs、design 和 tasks |
| [Grove UI 规范](.codex/skills/grove-ui-conventions/SKILL.md) | 产品组件、交互状态、桌面布局、小屏边界与验收规则 |

阅读顺序：先读产品蓝图与 `AGENTS.md`；实施功能时再读取相关主规格、活动 change 和代码。`openspec/changes/archive/` 是历史记录，不作为当前产品范围入口。

## 目录结构

```text
grove/
├── AGENTS.md          # 代理工作守则（产品铁律 + 工程约定）
├── README.md          # 唯一文档导航与本地开发入口
├── docs/              # 产品蓝图
├── openspec/          # OpenSpec 工作流（changes/ 与 specs/）
├── backend/           # FastAPI 后端（Python ≥3.12）
└── frontend/          # React 19 + TypeScript + Vite 前端
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

开始一个 change 前，应先确认它对应[产品蓝图第 18 节](docs/产品蓝图与功能优先级.md#18-建议的-openspec-change-顺序)中的哪一项；一次只实施一个 change，不顺带扩张后续阶段能力。
