## ADDED Requirements

### Requirement: 前端构建链
前端 MUST 使用 Vite + React 19 + TypeScript；MUST 提供 `npm run dev` 与 `npm run build`，构建 MUST 成功产出静态产物。

#### Scenario: 构建成功
- **WHEN** 在 `frontend/` 下执行 `npm run build`
- **THEN** 命令成功退出并生成 `dist/` 产物

### Requirement: 样式体系与基础组件
前端 MUST 配置 Tailwind 4，并初始化 shadcn/ui 基础（至少包含按钮组件与 `utils` 工具）；页面 MUST 使用 Tailwind 类名保证 390px 宽度下布局不横向溢出。

#### Scenario: 390px 宽度可用
- **WHEN** 以 390px 视口宽度渲染占位首页与健康检查页
- **THEN** 页面无横向滚动条，核心内容完整可见

### Requirement: 路由与页面
前端 MUST 使用 React Router 提供路由：`/` 为占位首页，`/health` 为健康检查页；健康检查页 MUST 调用后端 `GET /healthz` 并展示结果。

#### Scenario: 首页可访问
- **WHEN** 访问 `/`
- **THEN** 渲染占位首页，展示 Grove 项目名

#### Scenario: 健康检查页展示后端状态
- **WHEN** 访问 `/health` 且后端正常
- **THEN** 页面展示后端健康状态为正常

### Requirement: 数据获取
前端 MUST 集成 TanStack Query 作为服务端状态层，健康检查请求 MUST 通过 Query Client 发起；后端地址 MUST 可由 `VITE_API_BASE_URL` 环境变量配置。

#### Scenario: 查询客户端可用
- **WHEN** 前端应用加载
- **THEN** 根组件包含 TanStack Query 的 `QueryClientProvider`

### Requirement: 前端测试、lint 与格式
前端 MUST 提供 vitest 最小用例（至少覆盖一个组件渲染），执行 `npm test -- --run` MUST 通过；MUST 配置 eslint 与 prettier，执行 `npm run lint` MUST 通过。

#### Scenario: 测试与 lint 全绿
- **WHEN** 在 `frontend/` 下执行 `npm test -- --run` 与 `npm run lint`
- **THEN** 两条命令均成功退出且无失败项
