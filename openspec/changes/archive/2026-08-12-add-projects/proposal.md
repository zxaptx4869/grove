## Why

登录与 Workspace 隔离已就绪，但产品里还没有「放知识的地方」。提案明确目录是控制平面——人与 AI 共创的心智模型，采集、抽取、确认都围绕目录展开。本切片先建立多项目管理与目录树，让首个自用场景（装修）立即可用，也为后续采集/确认提供归属目标。

## What Changes

- 后端新增 `project-management` 能力：Workspace 下**多项目**（装修只是案例），项目列表/创建/重命名/删除，创建可选用「装修模板」或「空目录」。
- 后端新增 `node-tree` 能力：Node 自引用多级树（`parent_id` + `position` 排序字段），树读取、节点创建/重命名/删除/同父排序；不做跨父级移动。
- 模板资产：`backend/app/templates/decoration_knowledge_tree.md`（149 节点装修知识目录）作为种子源，运行时解析为树；**注册不自动创建项目**，由用户首次手动创建（可选装修模板或空目录）。
- 前端：项目管理页（列表/新建/重命名/删除）与项目页（NodeTree 真组件：展开/折叠、创建/重命名/删除、排序）；路由受登录守卫保护。
- 数据库迁移：新增 `projects` / `nodes` 表（SQLite 与 MySQL 8 兼容）。

## Capabilities

### New Capabilities

- `project-management`: Workspace 下多项目的 CRUD 与模板创建，跨空间隔离。
- `node-tree`: 目录树的读取、节点 CRUD、同父排序与模板种子生成。

### Modified Capabilities

- 无（不修改既有能力）。

## Impact

- 后端：Project / Node 模型与迁移；Markdown 模板解析器；项目与节点 API；所有查询经 `get_current_workspace` 过滤。
- 前端：API 客户端扩展；项目管理页与 NodeTree 组件；路由与守卫复用。
- 明确不包含：采集/抽取/确认/Entry；节点跨父级移动；共享与协作；多 Workspace 切换。
