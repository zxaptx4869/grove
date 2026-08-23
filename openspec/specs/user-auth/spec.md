# user-auth Specification

## Purpose
定义用户注册、登录、登出与会话管理，以及注册后默认 Workspace 的建立与当前用户依赖注入，保证请求可识别用户与隔离边界。
## Requirements
### Requirement: 用户注册
系统 MUST 提供注册接口：用户提交账号（username）与密码后创建用户，账号 MUST 全局唯一；密码 MUST 使用 argon2id 哈希存储，不得明文保存；注册成功 MUST 自动创建会话（注册即登录）。

#### Scenario: 注册成功并创建会话
- **WHEN** 提交一个未占用且符合格式的账号与密码
- **THEN** 创建用户成功，响应包含会话 Cookie，后续请求可携带该 Cookie 访问业务接口

#### Scenario: 重复账号注册失败
- **WHEN** 注册一个已存在的账号
- **THEN** 返回 409 Conflict，且不创建新用户

### Requirement: 用户登录与登出
系统 MUST 提供登录接口：账号与密码正确时创建会话并返回 HttpOnly Cookie；密码错误时返回 401。登出接口 MUST 使当前会话失效并清除 Cookie。

#### Scenario: 正确凭据登录成功
- **WHEN** 使用正确账号与密码调用登录接口
- **THEN** 返回成功且响应携带会话 Cookie

#### Scenario: 错误密码返回 401
- **WHEN** 使用错误密码调用登录接口
- **THEN** 返回 401 Unauthorized，不创建会话

#### Scenario: 登出后会话失效
- **WHEN** 已登录用户调用登出接口后，再携带原 Cookie 访问业务接口
- **THEN** 返回 401 Unauthorized

### Requirement: 会话 Cookie 安全属性
会话 Cookie MUST 设置 `HttpOnly`、`SameSite=Lax`；生产环境 MUST 同时设置 `Secure`。会话令牌在数据库中 MUST 以哈希形式存储（不存明文令牌）。

#### Scenario: Cookie 带安全属性
- **WHEN** 登录成功并检查响应中的 Set-Cookie
- **THEN** 包含 `HttpOnly` 与 `SameSite=Lax`，生产配置下包含 `Secure`

### Requirement: 认证依赖注入
后端 MUST 提供 `get_current_user` FastAPI 依赖：从 Cookie 解析会话并返回当前用户；无有效会话时业务接口 MUST 返回 401。业务路由 MUST 声明该依赖以启用认证保护。

#### Scenario: 未登录访问业务接口
- **WHEN** 未携带有效会话 Cookie 访问受保护接口
- **THEN** 返回 401 Unauthorized

#### Scenario: 已登录访问业务接口
- **WHEN** 携带有效会话 Cookie 访问受保护接口
- **THEN** 返回成功，且业务代码可获得当前用户
