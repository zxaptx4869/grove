## Why

Grove 目前没有认证与数据隔离：`/healthz` 之外没有任何用户概念，后续业务切片（采集、抽取、确认、归档、搜索）都依赖「当前是谁、数据属于哪个 Workspace」。先建立账号体系与 Workspace 隔离地基，业务数据从第一行起就带归属，避免上线后返工，也兑现提案里「数据从一开始按 Workspace 隔离」的承诺。

## What Changes

- 后端新增 `user-auth` 能力：注册、登录、登出；登录标识为**账号（username）+ 密码**，密码使用 argon2id 哈希；会话采用服务端 DB session + HttpOnly Cookie。
- 后端新增 `workspace-isolation` 能力：`Workspace` 模型与 `workspace_members` 多对多关系（v1 仅 owner）；注册时自动创建默认 Workspace；FastAPI 依赖注入提供 `get_current_user` / `get_current_workspace`，未登录访问业务 API 一律 401。
- 前端新增登录/注册页与路由守卫：未登录访问业务页面跳转登录；登录状态经 TanStack Query 管理。
- 更新 PROPOSAL.md 登录条目：由「邮箱 + 密码」调整为「账号 + 密码」，推广期再扩展邮箱/手机号/第三方登录（记录为设计决策）。
- 数据库迁移：新增 User / Workspace / WorkspaceMember / Session 表（SQLite 与 MySQL 8 兼容）。

## Capabilities

### New Capabilities

- `user-auth`: 账号 + 密码的注册、登录、登出与会话管理，会话 Cookie 与安全哈希。
- `workspace-isolation`: Workspace 数据归属模型与按空间过滤的依赖注入，保证跨 Workspace 读写是缺陷。

### Modified Capabilities

- 无（当前没有既有规格）。

## Impact

- 后端：新增依赖（argon2 哈希库）；新增认证/会话/Workspace 迁移与路由；`app/api` 增加认证路由；新增配置项（Cookie 安全参数、会话有效期）。
- 前端：新增 `src/pages/LoginPage.tsx`、`src/pages/RegisterPage.tsx`、认证 API 客户端、路由守卫；复用已有表单基座（react-hook-form + zod）。
- 文档：PROPOSAL.md 登录条目更新；change 的 design.md 记录「账号优先、推广期扩展」决策。
- 明确不引入：Project / Node / Source 等业务模型与采集/确认/目录逻辑；邮箱验证、密码找回、第三方登录、多空间切换与邀请。
