# frontend-foundation Specification

## Purpose
TBD - created by archiving change setup-project-foundation. Update Purpose after archive.
## Requirements
### Requirement: 前端构建链
前端 MUST 使用 Vite + React 19 + TypeScript；MUST 提供 `npm run dev` 与 `npm run build`，构建 MUST 成功产出静态产物。

#### Scenario: 构建成功
- **WHEN** 在 `frontend/` 下执行 `npm run build`
- **THEN** 命令成功退出并生成 `dist/` 产物

### Requirement: 样式体系与基础组件
前端 MUST 配置 Tailwind 4，并初始化 shadcn/ui 基础（至少包含按钮组件与 `utils` 工具）；产品业务页面 SHALL 按桌面知识工作台设计，从 1024px 视口宽度开始支持完整流程，不要求在手机宽度下重排或提供业务操作。

#### Scenario: 桌面工作台宽度可用
- **WHEN** 以 1280px 视口宽度渲染产品业务页面
- **THEN** 页面无非预期横向滚动，核心内容、导航和操作完整可见

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

### Requirement: Grove 仓库级 UI skill
仓库 MUST 包含 `.codex/skills/grove-ui-conventions/SKILL.md`，该 skill SHALL 在 Grove 前端实现、调整或 UI 验收任务中触发，并 SHALL 先读取产品蓝图索引、再按当前页面或交互任务读取相关专题，以 OpenSpec 定义产品行为、以 `frontend/src/index.css` 定义设计令牌、以现有组件代码定义接口，避免无差别加载全部蓝图文档或复制易漂移的第二份事实来源。

#### Scenario: 前端任务加载产品专属约束
- **WHEN** 代理实施或调整 Grove 前端页面、产品组件或交互状态
- **THEN** skill 能引导代理读取蓝图索引和当前任务相关专题，并检查 AI 候选与正式 Entry 区分、来源可达、状态完整、可访问性、桌面工作台布局和小屏产品边界

#### Scenario: skill 不加载无关专题
- **WHEN** 前端任务只涉及确认台、知识空间或其他单一产品领域
- **THEN** skill 不要求读取全部蓝图专题，而只加载索引、相关专题、当前规格、主题和代码

#### Scenario: skill 结构有效
- **WHEN** 使用 skill-creator 的 `quick_validate.py` 校验 `.codex/skills/grove-ui-conventions`
- **THEN** 校验成功且 skill 元数据与目录命名有效

### Requirement: 产品原型作为版本化设计参考
仓库 MUST 在 `docs/prototypes/` 保存可直接访问的 Grove 产品原型及说明文档。说明文档 SHALL 记录原型版本、覆盖页面、运行方式和权威边界，并 SHALL 明确原型中的静态数据与模拟交互不代表正式功能已经实现。

#### Scenario: 协作者访问当前产品原型
- **WHEN** 协作者从 README 进入产品原型
- **THEN** 能打开版本化 HTML、了解覆盖页面，并确认当前实现状态仍以 OpenSpec 主规格和正式代码为准

#### Scenario: 后续 change 引用原型
- **WHEN** 一个 OpenSpec change 实施原型覆盖的前端页面或交互
- **THEN** 其设计按需引用对应原型页面并记录有意偏离项，不要求读取或实现无关页面

#### Scenario: 正式前端采用原型设计
- **WHEN** 协作者将原型中的页面落地到正式前端
- **THEN** 使用现有 React、Tailwind、shadcn/ui 和 Lucide 实现，不直接复制原型的内联样式、演示脚本或静态业务状态

#### Scenario: 关键页面视觉验收
- **WHEN** 一个 change 完成原型所覆盖的关键桌面页面
- **THEN** 在该 change 范围内使用 1280px、1440px 和 1600px 视口与原型对照，并对有意差异保留可追溯说明

### Requirement: 端侧产品边界可追溯
仓库的产品蓝图、代理守则与 Grove UI skill MUST 一致声明：Web 只承担桌面完整业务流程，手机 Web 不属于业务流程验收范围；原生 App 上线前的小屏访问 SHALL 规划为统一的电脑访问提示，不提供简化版工作台或继续访问入口。

#### Scenario: 协作者确认 Web 支持范围
- **WHEN** 协作者准备设计或实施 Grove 产品页面
- **THEN** 能从权威文档中确认桌面支持宽度、手机 Web 非目标以及后续小屏阻断页要求
