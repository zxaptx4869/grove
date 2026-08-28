## Why

Grove 已有桌面 Web、后端与经过确认的移动端对话原型，但缺少可运行的 iOS/Android 原生工程，移动场景无法安全地复用既有 Workspace 与会话能力。本 change 建立最小的正式原生端基础，使后续移动端功能可以共用 Grove 后端与知识 Agent API，而不会演变为第二套业务模型或手机 Web。

## What Changes

- 新增独立的 Expo + React Native + TypeScript 移动工程，以 Expo Router、TanStack Query 和 SecureStore 建立原生应用壳。
- 新增移动注册、登录、登出与 Bearer 会话契约；会话继续使用现有 Session 表及哈希存储，Web Cookie 行为不变。
- 将认证依赖扩展为同时识别 Cookie 与 Bearer；当两者同时存在时 Bearer 优先，令牌无效时返回 401。
- 接通健康检查、身份、项目列表与移动登录流程；对话首页仅呈现真实 Workspace 和项目范围。
- 在技术与端侧边界专题中将原生 App 技术栈与本 change 的首批范围正式落定，保持 Web 小屏阻断策略不变。

## Capabilities

### New Capabilities

- `native-mobile-foundation`: 原生移动 App 工程、应用壳、真实项目范围和端侧运行配置。
- `mobile-session-auth`: 面向原生客户端的不透明会话 Token 签发、保存、验证与撤销。

### Modified Capabilities

- `user-auth`: 认证依赖与登出行为扩展为支持移动 Bearer 会话，并保持 Web Cookie 契约。

## Impact

- 新增 `mobile/` 独立 npm 工程及其测试、开发说明和环境变量示例。
- 修改后端认证 schemas、路由、依赖和测试；不修改 Session 数据库结构。
- 修改 `docs/产品蓝图/技术与端侧边界.md`，新增 OpenSpec 主规格。
- 新增 Expo、React Native、Expo Router、SecureStore、React Query、SVG、测试与 lint 相关依赖；不引入 monorepo、WebView 或云服务。
