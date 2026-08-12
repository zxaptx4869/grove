## 1. 数据模型与迁移（backend/）

- [x] 1.1 新增依赖：argon2 哈希库（首选 argon2-cffi，Python 3.14 不可用则回退 bcrypt 并记录）
- [x] 1.2 实现 `User` / `Workspace` / `WorkspaceMember` / `Session` ORM 模型（BigInteger 主键、String 长度，SQLite/MySQL 8 通用类型）
- [x] 1.3 编写 Alembic 迁移（含唯一约束、外键与索引），SQLite `upgrade head` 通过，MySQL 离线 SQL 校验通过
- [x] 1.4 在 `app/core/config.py` 增加 Cookie 与会话相关配置项（有效期、Secure 开关、Cookie 名）

## 2. 认证 API（backend/）

- [x] 2.1 实现密码哈希工具（argon2id 封装：hash / verify）
- [x] 2.2 实现会话工具（生成随机令牌、以 SHA-256 哈希入库、创建/校验/删除会话）
- [x] 2.3 实现 `POST /api/auth/register`（账号唯一校验、注册即登录）
- [x] 2.4 实现 `POST /api/auth/login` 与 `POST /api/auth/logout`
- [x] 2.5 实现 `get_current_user` 依赖；受保护业务路由示例（如 `GET /api/me`）验证 401/200
- [x] 2.6 pytest 覆盖：注册成功/重复账号 409/登录成功/错误密码 401/登出失效/Cookie 安全属性

## 3. Workspace 隔离（backend/）

- [x] 3.1 注册流程创建默认 Workspace 并登记 owner
- [x] 3.2 实现 `get_current_workspace` 依赖（当前用户 → 默认空间）
- [x] 3.3 提供隔离测试：两个用户各自的数据互不可见

## 4. 前端认证（frontend/）

- [x] 4.1 API 客户端增加认证接口与统一 401 处理
- [x] 4.2 实现登录页与注册页（react-hook-form + zod，复用基座组件）
- [x] 4.3 实现路由守卫与登录状态（TanStack Query）
- [x] 4.4 冒烟测试：登录/注册页可渲染；登录成功进入受保护页

## 5. 验证与收尾

- [x] 5.1 后端 `pytest -q` + `ruff check .` 全绿；前端 `npm test -- --run` + `npm run lint` + `npm run build` 全绿
- [x] 5.2 联调：注册 → 登录 → 访问受保护接口 → 登出，全链路可用（含 390px 布局检查）
- [x] 5.3 `openspec validate --all --strict` 通过 → archive 同步主规格
- [x] 5.4 在 `codex/add-user-auth` 分支提交并推送远端
