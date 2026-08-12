## Context

认证与 Workspace 隔离已完成（add-user-auth 已归档）。当前数据库已有 users / workspaces / workspace_members / sessions；业务层尚无任何内容模型。本切片引入项目与目录树，作为后续采集/抽取/确认的「归属目标」。首个自用场景为装修，模板为 149 节点的装修知识目录（用户提供的 Markdown）。

## Goals / Non-Goals

**Goals:**

- Workspace 下多项目 CRUD（装修只是案例，个人用户会有多个项目）。
- 多级目录树：读取、创建、重命名、删除（级联）、同父排序。
- 装修模板种子：创建项目时可选模板；注册不自动创建项目，由用户首次手动创建。
- 前端项目管理页 + NodeTree 真组件（替换占位），390px 可用。

**Non-Goals:**

- 节点跨父级移动（确认流需要时再做）。
- 采集/抽取/确认/Entry 等业务功能。
- 共享、协作、多 Workspace 切换。
- 模板的在线编辑与多模板管理（v1 内置一个模板）。

## Decisions

### D1：模板以 Markdown 为源，运行时解析
模板文件 `backend/app/templates/decoration_knowledge_tree.md` 是唯一内容源，解析器按约定解析：

- 从 `## 知识目录` 标题后开始；
- 每行 `- 名称 — 描述`（缩进两空格为一级）确定层级、名称与描述；
- 解析结果用于创建项目时批量插入节点。

**备选**：转成 JSON 种子——机器友好但失去可编辑性；Markdown 对产品负责人可维护，解析器用单测锁住（断言 149 节点与层级）。

### D2：Node 树模型：parent_id 自引用 + position 排序
`Node(id, project_id, parent_id, name, description, position)`；`position` 为同级内整数序号。树读取一次加载整棵项目树（149 节点量级，内存组装即可）。

### D3：多项目模型，注册不自动建项目
`Project(workspace_id, name, template)`；注册只建 Workspace，不创建项目；用户首次进入项目页时手动创建项目（可选手装修模板或空目录）。v1 UI 支持多项目列表。

**备选**：注册自动建「房子装修」示例项目——开箱即用但会污染新用户空间；按用户「装修只是案例、个人有多项目场景」的定位，保持空间干净，首次手动创建。

### D4：删除级联在应用层递归
SQLite 外键默认不启用（PRAGMA off），跨库行为不一致；因此在应用层递归删除节点/项目，并补测试。MySQL 的 `ondelete=CASCADE` 仅作兜底。

### D5：排序交互：原生拖拽 + 上下移按钮
桌面用原生 HTML5 拖拽（无新依赖）；键盘与 390px 触屏场景用上移/下移按钮（符合 UI 规范的键盘可达要求）。两种交互都调用同一 reorder API。

### D6：前端结构与路由
`/projects` 项目管理页（列表/新建/重命名/删除，模板选择）；`/projects/:id` 项目页（NodeTree）。均套 `ProtectedRoute`；NodeTree 为数据驱动受控组件（props: tree, callbacks），替换 `src/components/features/` 中同名占位。

## Risks / Trade-offs

- [模板解析格式漂移] → 解析器单测锁定节点数与层级；模板头部注释写明格式约定。
- [递归删除在深树下的性能/栈风险] → 树深有限（当前模板最深约 4 级），应用层递归 + 测试；后续可换 WITH RECURSIVE。
- [原生 HTML5 拖拽在触屏不可用] → 上下移按钮兜底，且满足键盘可达验收。
- [首屏无项目，首次使用多一步] → 项目页空状态引导「创建项目」，一键选用装修模板；已记录决策。

## Migration Plan

1. 新增 `projects` / `nodes` 表迁移（BigInteger 主键 + with_variant(Integer, "sqlite")，沿用既有模式），SQLite 实跑 + MySQL 离线 SQL 校验。
2. 后端先完成：解析器 → 种子 → 项目/节点 API → pytest。
3. 前端接入：API 客户端 → 项目管理页 → NodeTree → 冒烟测试。
4. `openspec validate --all --strict` → archive → 本地提交（按工作守则，等待用户验证后再推送/合并）。

## Open Questions

- 无阻塞项。
