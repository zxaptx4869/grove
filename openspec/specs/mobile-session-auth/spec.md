# mobile-session-auth Specification

## Purpose
TBD - created by archiving change add-native-mobile-foundation. Update Purpose after archive.
## Requirements
### Requirement: 移动注册与登录契约
系统 MUST 提供仅供原生移动客户端使用的注册与登录接口。成功时 MUST 创建现有 `sessions` 表中的会话，并返回随机、不透明的 Session Token；数据库仅存储 Token 哈希。既有 Web 注册与登录接口不得返回 Token。

#### Scenario: 移动注册返回不透明 Token
- **WHEN** 客户端以有效账号密码调用移动注册接口
- **THEN** 系统创建用户、默认 Workspace 与会话，并只在移动响应体中返回 Token

#### Scenario: Web 登录不泄露 Token
- **WHEN** 客户端调用既有 Web 注册或登录接口
- **THEN** 响应维持用户信息和 HttpOnly Cookie，响应体不包含会话 Token

### Requirement: Bearer 会话验证与优先级
受保护 API MUST 支持 `Authorization: Bearer <token>`，并与既有 Cookie 会话共存。请求同时携带二者时 MUST 使用 Bearer；Bearer 缺失、格式错误、无效或过期时 MUST 返回 401，不得回退到 Cookie。

#### Scenario: Bearer 可访问当前用户和项目
- **WHEN** 移动客户端携带有效 Bearer 调用 `/api/me` 与 `/api/projects`
- **THEN** 系统返回该 Token 用户所属 Workspace 的身份与项目，且不包含其他 Workspace 数据

#### Scenario: 无效 Bearer 不回退 Cookie
- **WHEN** 请求同时携带有效 Cookie 和无效 Bearer
- **THEN** 系统返回 401 Unauthorized

### Requirement: 移动登出与本地会话恢复
移动登出接口 MUST 撤销当前 Bearer 对应服务端 Session。App MUST 将 Token 保存到 `expo-secure-store`，启动时验证 `/api/me`；验证返回 401 时 MUST 清理本地 Token 并回到登录页。

#### Scenario: 移动登出使 Token 失效
- **WHEN** 移动客户端携带 Bearer 调用移动登出后再次使用原 Token 请求受保护 API
- **THEN** 系统返回 401，且客户端清理 SecureStore 中的 Token

