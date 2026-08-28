## Context

Grove 现有 FastAPI 后端将随机会话 Token 的 SHA-256 哈希保存到 `sessions` 表，Web 注册、登录与受保护 API 仅使用 HttpOnly Cookie。仓库存在经确认的 390×844 移动对话原型，但尚无 iOS/Android 工程。技术与端侧边界仍将原生 App 标为“P3 再确定”。

本 change 是正式原生端地基：共用 Grove 后端、用户、Workspace、Project、Session 和未来知识 Agent API；不复制或包裹 Web。视觉基线来自原型及 Web 语义色：浅灰绿背景、白色表面、绿色主操作、四项原创线性底栏图标、范围栏与安全区壳层。

## Goals / Non-Goals

**Goals:**

- 以当前 Expo managed/CNG、React Native、TypeScript 和 Expo Router 建立可独立验证的 `mobile/`。
- 用 SecureStore + Bearer 接入真实身份与项目数据，复用服务端 Session 哈希存储和 Workspace 隔离。
- 建立对话默认首页、范围切换、四栏导航、键盘避让和明确未接入状态。
- 将原生端技术决策同步至权威端侧专题。

**Non-Goals:**

- Reader/知识 Agent、连续问答、Entry/Source/Candidate/目录读写、采集、相机、系统分享、离线库、推送、EAS、签名、商店或云部署。
- 手机 Web 业务适配、WebView、第二套领域模型、monorepo 与复杂共享组件库。

## Decisions

### Expo managed/CNG 与独立 npm 工程

采用稳定 Expo SDK 的 blank TypeScript 模板和 Expo Router，保留 CNG，只有 SDK 工具在 `prebuild` 时生成原生目录。选择它是因为 Router、Safe Area、SecureStore 与原生导航可受 Expo 管理；不提交手工维护的 `ios/`/`android/`。替代的 bare React Native 增加原生维护成本，WebView 不符合产品边界。

### 会话：同一 Session 表，不透明 Bearer

移动 `/api/auth/mobile/register`、`/login` 返回 `{ user, token }`。Token 使用既有随机生成器，落库前同样哈希；移动登出按 Bearer 查找并删除该 Session。Web `/register`、`/login` 保持 Cookie-only。

`get_current_user` 读取 `Authorization`：只要头存在，即严格校验 `Bearer <token>` 并忽略 Cookie；无头时走 Cookie。此策略可避免一个失效或被错误注入的 Bearer 悄然降级为其他人的 Cookie 会话。

### 移动网络客户端与状态恢复

集中 API 客户端从 `EXPO_PUBLIC_API_BASE_URL` 构造 URL，设置超时、标准错误对象和 Bearer 注入。认证 Provider 在启动时从 SecureStore 读取 Token 并调用 `/api/me`；401 删除 Token。TanStack Query 使用 `staleTime: 0`，以 `/api/me` 和 `/api/projects` 的真实状态作为唯一数据来源。

### 视觉与交互边界

从 Web 令牌提取颜色，不复制 CSS；使用 `SafeAreaView`、原生 `KeyboardAvoidingView`、可滚动内容、屏幕焦点判断和自绘 SVG 图标。对话范围仅列出“全部知识”和项目；未接入栏目是明确的空状态。原型中 Agent 卡片、静态任务与知识项均不迁移。

## Risks / Trade-offs

- [本机没有 Xcode/Simulator 或 Android SDK] → 以 typecheck、lint、Jest 与后端集成测试验证；验证文档明确记录未运行的平台，不声称设备走查通过。
- [开发地址在模拟器/真机不同] → 不提供默认 localhost，README 列出 iOS Simulator、Android Emulator、局域网 IP 与 HTTPS 的明确配置。
- [Bearer 令牌被记录] → 客户端仅使用 SecureStore，服务端绝不记录明文 Token；错误模型不包含 Token。
- [Cookie/Bearer 冲突] → Bearer 优先且无效时 401，并由后端测试覆盖。

## Migration Plan

1. 先发布后端兼容认证依赖和移动专属契约，既有 Cookie 请求不变。
2. 配置移动 API 地址后以本地 Expo 开发服务连接同一后端。
3. 回滚时删除移动客户端或停止使用移动路由；会话表无 schema 改动，已签发 Token 可按 Session 正常撤销。

## Open Questions

- EAS、应用签名、深链、系统分享、相机、推送和商店发布不在本 change 中，需后续 change 单独决策。
