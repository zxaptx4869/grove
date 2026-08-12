## Context

Grove 工程骨架已完成（FastAPI 应用工厂、async SQLAlchemy、Alembic、前端基座），但没有任何认证与数据归属概念。本 change 建立账号体系与 Workspace 隔离地基，供后续业务切片（采集/抽取/确认/归档）直接复用。当前无活动业务表，迁移从零开始。

## Goals / Non-Goals

**Goals:**

- 账号（username）+ 密码注册、登录、登出；密码安全哈希；会话 Cookie。
- `get_current_user` / `get_current_workspace` 依赖注入；未登录业务接口 401。
- Workspace 模型与注册自动创建默认空间；数据按空间过滤。
- 前端登录/注册页与路由守卫，复用表单基座。

**Non-Goals:**

- 邮箱验证、密码找回、邮箱/手机号/第三方登录（推广期扩展，仅留设计预留）。
- 多 Workspace 切换、邀请、协作与复杂权限（登录后仍是个人使用）。
- 一切业务模型与功能（Project / Node / Source / ProcessingTask / Extraction / Entry）。

## Decisions

### D1：登录标识用账号（username），推广期再扩展
决策记录（2026-08-12）：v1 自用从简，登录标识为唯一账号字符串 + 密码；不发邮箱/手机号/第三方登录。推广需求出现时再扩展登录标识（邮箱/手机号/第三方），设计上保持「登录标识可扩展」抽象，但**不为未来加空字段**（YAGNI）。

**备选**：沿用提案原「邮箱 + 密码」——会连带邮箱验证、找回密码等配套成本，v1 不划算。PROPOSAL.md 对应条目已同步更新。

### D2：会话用服务端 DB session，而非 JWT
随机令牌存 `Session` 表（令牌以 SHA-256 哈希存储，Cookie 里放明文令牌），支持随时撤销、登出即失效、未来设备管理。

**备选**：JWT signed cookie——无状态但撤销麻烦（需黑名单），个人管家场景可控可审计更重要。

### D3：密码哈希用 argon2id
首选 `argon2-cffi`（argon2id 参数默认即可）。若 Python 3.14 无可用 wheel/编译失败，回退 `bcrypt`，两者均为公认安全哈希；实施时验证并锁定。

### D4：注册即登录
注册成功后直接创建会话返回 Cookie，省去「注册后再登录」一步，贴合自用体验。

### D5：Workspace 模型预留多对多，v1 只实现 owner
建 `Workspace` 与 `workspace_members`（user_id + workspace_id + role）多对多关系，注册时创建默认空间并把用户登记为 owner。v1 不做邀请/切换 UI；推广时加成员即可，不动表结构。

**备选**：User 直接挂 workspace_id 外键——更简单，但推广期要拆表迁移，成本更高。

### D6：认证与空间依赖注入
`get_current_user`（Cookie → Session → User）与 `get_current_workspace`（User → 默认空间）作为 FastAPI 依赖；业务路由声明依赖即受保护。骨架中的 `/healthz` 保持公开。

### D7：前端认证流
新增 `/login`、`/register` 页（react-hook-form + zod），TanStack Query mutation 调认证接口；路由守卫：未登录访问受保护页跳转 `/login`。401 由 API 客户端统一处理（清除会话状态并跳登录）。

### D8：安全与 Cookie 细节
`HttpOnly` + `SameSite=Lax`，生产 `Secure`；CSRF 防护用「自定义请求头校验」（前端 API 请求带 `X-Requested-With` 等头，同源即可过，跨站表单无法携带）；会话有效期 30 天固定。

## Risks / Trade-offs

- [argon2 在 Python 3.14 的兼容性未知] → 实施时先装验证；失败回退 bcrypt 并记录。
- [多对多预留被诟病过度设计] → 已权衡：推广必做，现在建表成本几乎为零，未来拆表成本高。
- [Cookie/CSRF 配置错误导致安全漏洞] → HttpOnly + SameSite + Secure（生产）+ 自定义头校验三层，测试覆盖 Cookie 属性断言。
- [会话表随使用增长] → 登出即删；过期清理可在后续 change 补定时任务，v1 不阻塞。
- [账号无邮箱绑定，找回困难] → v1 自用可接受；推广期扩展登录标识时一并补找回，已记录在决策。

## Migration Plan

1. 本 change 在 `codex/add-user-auth` 分支实施（待创建）。
2. 迁移新增 `users` / `workspaces` / `workspace_members` / `sessions` 四张表，SQLite 与 MySQL 8 兼容（BigInteger 主键、String 长度、utf8mb4）。
3. 后端先于前端完成并测通（pytest：注册/登录/登出/401/隔离）；前端登录页与守卫接入。
4. `openspec validate --all --strict` → archive → 提交推送。回滚：认证未上生产，表可随迁移回滚。

## Open Questions

- 无阻塞项。会话有效期（30 天）与「注册即登录」如需调整，属配置/体验微调，实施时按默认值执行并在 PR 说明。
