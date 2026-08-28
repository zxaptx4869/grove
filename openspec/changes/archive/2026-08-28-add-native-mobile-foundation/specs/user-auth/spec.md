## MODIFIED Requirements

### Requirement: 用户登录与登出
系统 MUST 提供 Web 登录接口：账号与密码正确时创建会话并返回 HttpOnly Cookie；密码错误时返回 401。系统 MUST 同时提供移动 Bearer 登出接口，使当前 Bearer 会话失效。Web 登出 MUST 使当前 Cookie 会话失效并清除 Cookie。

#### Scenario: 正确凭据登录成功
- **WHEN** 使用正确账号与密码调用 Web 登录接口
- **THEN** 返回成功且响应携带会话 Cookie，响应体不包含会话 Token

#### Scenario: 错误密码返回 401
- **WHEN** 使用错误密码调用登录接口
- **THEN** 返回 401 Unauthorized，不创建会话

#### Scenario: 登出后会话失效
- **WHEN** 已登录用户调用与当前凭据类型对应的登出接口后，再携带原凭据访问业务接口
- **THEN** 返回 401 Unauthorized

### Requirement: 认证依赖注入
后端 MUST 提供 `get_current_user` FastAPI 依赖：从 Cookie 或 `Authorization: Bearer` 解析会话并返回当前用户；无有效会话时业务接口 MUST 返回 401。请求存在 Bearer 时 MUST 优先且严格使用 Bearer，不得因其无效而回退 Cookie。业务路由 MUST 声明该依赖以启用认证保护。

#### Scenario: 未登录访问业务接口
- **WHEN** 未携带有效会话 Cookie 或 Bearer 访问受保护接口
- **THEN** 返回 401 Unauthorized

#### Scenario: 已登录访问业务接口
- **WHEN** 携带有效会话 Cookie 或 Bearer 访问受保护接口
- **THEN** 返回成功，且业务代码可获得当前用户

#### Scenario: Bearer 优先于 Cookie
- **WHEN** 同一请求同时携带 Cookie 与 Bearer
- **THEN** 系统仅依据 Bearer 解析会话，Bearer 无效时返回 401
