## Context

本 change 对应蓝图中“产品基线修正”第一项，并参考原型的项目列表、项目首页、目录树和全局导航结构。当前后端已具备账号/会话、默认 Workspace、项目 CRUD、目录树读取/创建/编辑/删除/排序；但 `Project` 只有名称和模板字段，模板创建仍是旧产品路径，前端页面仍是早期骨架，且小屏可能进入业务界面。

## Goals / Non-Goals

**Goals:** 建立可真实使用的登录后桌面壳、项目列表与四态生命周期、项目工作台基础结构、默认空目录和手动目录维护；保留 Workspace 隔离与现有认证协议。

**Non-Goals:** Source/Attachment、Processing Task、Extraction、Candidate、Entry、AI 推荐、Directory Agent、AI 阅读、搜索、思维导图、手机 Web 业务界面和未来功能占位页。

## Decisions

### 现有代码保留、重写和删除

- 保留：`User`、`Workspace`、`Session` 模型及 Cookie 会话依赖；`get_current_workspace` 的查询边界；项目/节点的 SQLAlchemy 基础关系；`knowledge_tree` 的树装配和排序逻辑；前端 API 请求封装、认证 hooks、TanStack Query、shadcn/ui 基础组件和 NodeTree 的数据递归思路。
- 重写：项目 schema/API 的模板参数改为可选目标与背景、状态筛选和生命周期；目录更新接口扩展父节点移动校验；`AppShell`、登录注册页面、项目列表和项目工作台页面按原型信息层级重新实现。
- 删除：正式 UI 中的装修模板选择、模板徽标和旧页面的移动端重排；保留模板解析文件与服务代码仅用于历史迁移兼容，不再从新建接口调用。

### 页面结构

采用原型的安静工作台结构：左侧全局导航与最近项目，中间项目列表或项目工作区，项目工作区内以项目顶栏、状态/说明和目录管理为主。目录为空时并列展示“手动创建第一个节点”和“与 AI 共创目录”两个入口；后者仅显示未实现提示或禁用态，不创建草稿。

与原型有意不同：本轮不渲染收集箱、确认台、知识空间、AI 阅读、搜索结果和目录草稿等静态演示页；未实现的全局导航不进入业务路由，避免把原型中的模拟数据误认为能力。登录注册保持工具页而不是营销 Hero。

### API 与数据迁移

- `Project` 新增 `description`（可空 Text）和 `status`（字符串，默认 `active`）字段；API 使用 `active/paused/completed/archived` 稳定值，前端显示中文状态。
- `POST /api/projects` 接受 `name`、可选 `description`，忽略并移除 `template` 业务路径；新项目不创建节点。
- `GET /api/projects` 增加可选 `status` 查询参数；新增 `PATCH /api/projects/{id}/status`，归档恢复使用同一接口。
- 节点更新请求增加可选 `parent_id`；服务层加载项目内完整祖先/后代集合，拒绝自指、后代和跨项目父节点，重新压紧旧父级位置并追加到新父级。
- Alembic 新迁移为既有项目填充 `description=NULL`、`status='active'`，保留 `template` 列以兼容旧数据但不再从 API 暴露模板选择。无法可靠识别历史装修项目时不自动删除节点，避免数据损失。

### 前端状态与边界

应用根部先判断 `window.innerWidth < 1024`，阻断页不挂载认证/项目 Query；宽度变化时监听 resize 并卸载工作台。业务数据全部来自 Query hooks。破坏性项目/目录删除使用 Dialog 二次确认，loading 时稳定禁用按钮，错误状态邻近提供重试。

## Risks / Trade-offs

- [历史模板数据仍存在] → 迁移只新增字段，不删除旧节点；新 UI 不再依赖模板列。
- [SQLite/MySQL 状态字段差异] → 使用短字符串和应用层枚举校验，迁移仅使用通用 `add_column`/`server_default`。
- [小屏 resize 竞态] → 壳层统一控制渲染边界，Query 仅在桌面分支挂载。
- [删除目录影响未知] → 本轮无 Entry 表，仍显示子树节点数量并要求确认；后续 Entry change 再增加来源/知识影响校验。

## Migration Plan

1. 先执行 Alembic 迁移并运行后端测试；旧数据的 `template` 保留。
2. 部署后端兼容新字段，再切换前端壳与页面。
3. 回滚时可回退前端，数据库新增列可保留；不执行破坏性数据回滚。

## Open Questions

- 归档后恢复是否需要恢复到归档前状态；本轮按蓝图约定统一恢复为进行中。
- Directory Agent 上线时“与 AI 共创目录”入口应升级为对话抽屉还是独立工作台；留待 P1 change 决定。
