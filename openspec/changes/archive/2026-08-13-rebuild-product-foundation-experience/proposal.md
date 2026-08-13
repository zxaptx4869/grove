## Why

Grove 已有账号、Workspace、项目和目录的技术基础，但当前产品体验仍沿用早期骨架：项目被当作模板目录容器，缺少生命周期与项目背景，前端也没有稳定的桌面工作台壳和小屏边界。现在需要先把最小可信的基础体验重新整理好，避免后续采集、确认和知识空间能力建立在错误的信息架构上。

## What Changes

- **BREAKING** 项目创建改为名称 + 可选目标与背景，默认生成空目录，不再把装修模板作为正式创建路径。
- 为项目增加进行中、暂停、已完成、已归档四态生命周期，支持列表筛选、状态变更、归档隐藏与恢复。
- 重建登录、注册、退出和认证后的全局应用壳，提供项目、收集箱、搜索、账户的导航骨架；本轮仅实现项目业务入口。
- 重建项目列表和项目工作台基础结构，包含状态筛选、空状态、新建项目和目录管理入口。
- 为目录节点补齐手动创建、编辑、移动、排序和删除；删除前显示影响并要求确认。
- 提供“与 AI 共创目录”入口，明确其为后续能力入口，本轮不调用 Directory Agent、不产生目录草稿。
- 低于 1024px 时在路由层阻断业务工作台，只展示电脑访问提示。

明确 Non-Goals：Source、Attachment、Processing Task、Extraction、Candidate、Entry、AI 推荐、Directory Agent 实现、AI 阅读、搜索结果、思维导图、手机 Web 业务界面及未来能力占位页面。

## Capabilities

### New Capabilities

- `product-shell`: 认证后的全局桌面应用壳、登录注册退出交互和小屏阻断。

### Modified Capabilities

- `project-management`: 项目说明、生命周期、默认空目录、状态筛选、归档恢复和工作台基础数据。
- `node-tree`: 节点移动以及包含子树时的删除确认与完整 Workspace/Project 校验。
- `frontend-foundation`: React 应用路由、桌面信息架构、真实 API 状态和完整交互状态要求。

## Impact

- 后端：`Project` 模型、Pydantic schema、项目 API、Alembic 新迁移及相关测试。
- 前端：应用路由与壳、认证页面、项目列表/工作台/目录管理页面、API hooks、状态组件和响应式边界测试。
- 保留并复用会话 Cookie、`get_current_workspace`、Workspace 查询边界、`NodeTree` 数据结构、TanStack Query 和现有 shadcn/ui 基础组件；移除模板创建 UI 与旧项目页面布局。
- 不新增外部依赖，不改变 Workspace 隔离策略和既有认证协议。
