## MODIFIED Requirements

### Requirement: 路由与页面
前端 MUST 使用 React Router；认证路由包含 `/login` 与 `/register`，受保护的桌面路由包含 `/projects` 和 `/projects/:projectId`，全局壳提供项目、收集箱、搜索、账户导航。`/health` 保持健康检查页。

#### Scenario: 未登录访问受保护路由
- **WHEN** 未登录用户访问 `/projects`
- **THEN** 页面跳转到 `/login`，不加载项目数据

#### Scenario: 已登录访问项目工作台
- **WHEN** 已登录用户访问 `/projects/:projectId`
- **THEN** 显示项目基础信息和目录树管理入口

#### Scenario: 首页可访问
- **WHEN** 用户访问 `/`
- **THEN** 路由根据认证状态进入项目列表或登录页

#### Scenario: 健康检查页展示后端状态
- **WHEN** 访问 `/health` 且后端正常
- **THEN** 页面展示后端健康状态为正常

### Requirement: 数据获取
前端 MUST 使用 TanStack Query 访问真实认证、项目和目录 API；查询需要展示 loading、empty、error、retry 和 disabled 状态，变更成功后使相关查询失效并刷新。

#### Scenario: 项目列表为空
- **WHEN** 项目接口返回空数组
- **THEN** 页面显示空状态并提供新建项目动作

#### Scenario: 项目请求失败
- **WHEN** 项目或目录接口返回错误
- **THEN** 页面显示邻近错误说明与重试按钮，不显示静态项目数据

#### Scenario: 查询客户端可用
- **WHEN** 前端应用加载
- **THEN** 根组件包含 TanStack Query 的 `QueryClientProvider`

### Requirement: 样式体系与基础组件
产品业务页面 SHALL 使用 React 19、Tailwind 4、shadcn/ui 和 Lucide，采用安静紧凑的桌面工作台布局；从 1024px 起完整可用，低于 1024px 由 `product-shell` 规格阻断。

#### Scenario: 桌面项目工作台宽度可用
- **WHEN** 以 1280px、1440px 或 1600px 视口渲染项目页面
- **THEN** 导航、列表、工作区和主要操作无非预期横向滚动、遮挡或文字溢出

#### Scenario: 桌面工作台宽度可用
- **WHEN** 以 1280px 视口宽度渲染产品业务页面
- **THEN** 页面无非预期横向滚动，核心内容、导航和操作完整可见
