## ADDED Requirements

### Requirement: 后端应用工厂与配置
后端 MUST 提供 FastAPI 应用工厂 `create_app`；配置 MUST 使用 pydantic-settings，支持从环境变量与 `.env` 读取；`DATABASE_URL` 默认值 MUST 为 `sqlite+aiosqlite:///./grove.db`，生产环境 MUST 可切换为 MySQL 8 连接串。`.env.example` MUST 提供完整键位模板，`.env` 不得提交。

#### Scenario: 默认配置启动成功
- **WHEN** 不设置任何环境变量，通过 `create_app()` 创建应用
- **THEN** 应用成功创建，`DATABASE_URL` 使用默认 SQLite 连接串

#### Scenario: 环境变量覆盖配置
- **WHEN** 设置 `DATABASE_URL` 为 MySQL 8 连接串后创建应用
- **THEN** 应用配置中的数据库连接串为所设置的 MySQL 值

### Requirement: 健康检查接口
后端 MUST 提供 `GET /healthz`，返回 HTTP 200 与 JSON 响应，内容包含 `status` 字段且值为 `ok`。

#### Scenario: 健康检查返回 200
- **WHEN** 调用 `GET /healthz`
- **THEN** 返回 HTTP 200，JSON 中 `status` 为 `ok`

### Requirement: CORS 配置
后端 MUST 配置 CORS，允许前端开发服务器（`http://localhost:5173` 与 `http://127.0.0.1:5173`）跨域访问；允许来源 MUST 可通过环境变量配置。

#### Scenario: 前端开发源可跨域访问
- **WHEN** 从 `http://localhost:5173` 发起带 Origin 的请求
- **THEN** 响应包含允许该来源的 CORS 头

### Requirement: 异步数据库基础设施
后端 MUST 基于 async SQLAlchemy 2 提供引擎、`async_sessionmaker` 会话工厂与声明式 `Base`；FastAPI 依赖注入 SHALL 提供会话获取方式，供后续业务 change 使用。

#### Scenario: 依赖注入获取数据库会话
- **WHEN** 在测试中调用数据库会话依赖
- **THEN** 返回可用的 async SQLAlchemy 会话对象

### Requirement: Alembic 迁移骨架
后端 MUST 配置 Alembic，支持 `DATABASE_URL` 切换 SQLite 与 MySQL 8；初始迁移 MUST 能同时在这两种数据库上执行，并 SHALL 在迁移文件中以注释标注方言差异。

#### Scenario: SQLite 迁移可执行
- **WHEN** 以默认 SQLite 连接串执行 `alembic upgrade head`
- **THEN** 命令成功，数据库版本表创建完成

#### Scenario: MySQL 迁移配置可校验
- **WHEN** 以 MySQL 8 连接串执行迁移配置的编译/校验
- **THEN** 配置与迁移脚本不包含 SQLite 专属语法，方言差异有注释说明

### Requirement: 后端测试与静态检查
后端 MUST 提供 pytest 最小用例（覆盖健康检查），执行 `pytest -q` MUST 全部通过；MUST 提供 ruff 配置，执行 `ruff check .` MUST 无错误。

#### Scenario: 测试与 lint 全绿
- **WHEN** 在 `backend/` 下执行 `pytest -q` 与 `ruff check .`
- **THEN** 两条命令均成功退出且无失败项
