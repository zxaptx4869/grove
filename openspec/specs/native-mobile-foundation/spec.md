# native-mobile-foundation Specification

## Purpose
TBD - created by archiving change add-native-mobile-foundation. Update Purpose after archive.
## Requirements
### Requirement: 独立原生移动工程
系统 MUST 在仓库 `mobile/` 提供独立 npm 管理的 Expo managed/CNG React Native TypeScript 工程，使用 Expo Router、TanStack Query、原生组件和 `react-native-svg`。工程不得使用 WebView、Web DOM、Tailwind Web 页面或 shadcn Web 组件，也不得要求根级 workspace 或重构既有 frontend。

#### Scenario: 移动工程可进行静态验证
- **WHEN** 在 `mobile/` 安装依赖后运行 lint、typecheck 和测试命令
- **THEN** 三个命令均可独立执行且不依赖 frontend 的包管理配置

### Requirement: 原生应用壳与导航
登录后系统 MUST 提供“对话、收集、待处理、知识”四栏原生底部导航，默认页为对话。应用 MUST 使用安全区、可滚动内容和键盘避让；对话输入获得焦点时 MUST 隐藏底部导航且输入区不得被软件键盘遮挡。

#### Scenario: 对话为默认首页
- **WHEN** 已验证会话的用户启动应用
- **THEN** 系统显示对话页和四栏底部导航，且对话栏目处于选中状态

#### Scenario: 键盘展开时保护输入区
- **WHEN** 用户在对话页聚焦输入框
- **THEN** 底部导航隐藏，输入区保持在可见可操作区域，长内容仍可垂直滚动

### Requirement: 真实 Workspace 范围与项目数据
移动对话首页 MUST 读取 `/api/me` 的真实 Workspace 与 `/api/projects` 的真实项目列表。用户可见知识范围 MUST 只有 Workspace 的“全部知识”和具体项目，不得暴露目录节点范围。本 change 不得调用 Reader 或模拟 Agent 回答。

#### Scenario: 项目加载后切换范围
- **WHEN** 认证用户打开范围选择并选中一个项目或“全部知识”
- **THEN** 当前范围立即以清晰文字显示，选择项只包含全部知识和该 Workspace 的项目

#### Scenario: 未接入业务栏目不伪造数据
- **WHEN** 用户进入收集、待处理或知识栏目
- **THEN** 系统显示该能力尚未接入的真实状态与下一步说明，而不是静态业务记录

### Requirement: 移动端地址与运行说明
移动工程 MUST 通过 `EXPO_PUBLIC_API_BASE_URL` 获取 API 地址，禁止硬编码 localhost，并提供环境变量示例和开发说明，覆盖模拟器、局域网真机与后续 HTTPS 地址配置。

#### Scenario: 缺少 API 地址时有明确反馈
- **WHEN** 未配置有效的 `EXPO_PUBLIC_API_BASE_URL`
- **THEN** 应用显示可理解的配置错误，且不尝试向硬编码 localhost 发起请求
