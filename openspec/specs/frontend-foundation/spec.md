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
产品业务页面 SHALL 使用 React 19、Tailwind 4、shadcn/ui 和 Lucide，采用安静紧凑的桌面工作台布局；从 1024px 起完整可用，低于 1024px 由 `product-shell` 规格阻断。按钮 SHALL 使用图标表达熟悉操作，目录与项目行的次级操作 SHALL 收纳到上下文菜单，不得平铺工程缩写文字按钮。

#### Scenario: 桌面项目工作台宽度可用
- **WHEN** 以 1280px、1440px 或 1600px 视口渲染项目页面
- **THEN** 导航、列表、工作区和主要操作无非预期横向滚动、遮挡或文字溢出

#### Scenario: 桌面工作台宽度可用
- **WHEN** 以 1280px 视口宽度渲染产品业务页面
- **THEN** 页面无非预期横向滚动，核心内容、导航和操作完整可见

#### Scenario: 目录操作紧凑且可理解
- **WHEN** 用户浏览非空目录树
- **THEN** 节点行显示展开、名称和必要的状态，新增、编辑、移动、排序与删除通过图标或上下文菜单进入，且图标具有可访问名称

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
仓库 MUST 在 `docs/prototypes/` 保存可直接访问的 Grove 产品原型及说明文档。说明文档 SHALL 记录原型版本、覆盖页面、运行方式和权威边界，并 SHALL 明确原型中的静态数据与模拟交互不代表正式功能已经实现。实施原型覆盖页面时 MUST 以同一视口截图对照验证页面结构、几何、颜色、字体、密度、对齐、控件形态和关键状态，不得只验证 DOM 存在、路由可达或大致结构相似。

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
- **THEN** 在 1280px、1440px 和 1600px 生成正式页面与原型同视口截图，逐项核对侧栏与顶栏尺寸、内容起点、背景层级、字体、间距、行高、控件尺寸和交互状态，并保存截图路径与有意偏离说明

#### Scenario: 原型包含未实现业务数据或动作
- **WHEN** 原型截图包含当前 OpenSpec 尚未实现的统计、按钮或导航能力
- **THEN** 正式页面保持相同的必要布局层级，但不以静态数据或可操作假入口填充，并在 change 设计中记录视觉偏离

### Requirement: 端侧产品边界可追溯
仓库的产品蓝图、代理守则与 Grove UI skill MUST 一致声明：Web 只承担桌面完整业务流程，手机 Web 不属于业务流程验收范围；原生 App 上线前的小屏访问 SHALL 规划为统一的电脑访问提示，不提供简化版工作台或继续访问入口。

#### Scenario: 协作者确认 Web 支持范围
- **WHEN** 协作者准备设计或实施 Grove 产品页面
- **THEN** 能从权威文档中确认桌面支持宽度、手机 Web 非目标以及后续小屏阻断页要求
