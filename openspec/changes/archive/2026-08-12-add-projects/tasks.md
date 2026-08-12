## 1. 后端模型与迁移

- [x] 1.1 实现 `Project` / `Node` ORM 模型（workspace_id、parent_id 自引用、position、name、description）
- [x] 1.2 编写 Alembic 迁移（BigInteger 主键 + with_variant(Integer,"sqlite")），SQLite `upgrade head` 与 MySQL 离线 SQL 校验通过

## 2. 模板解析与种子

- [x] 2.1 模板资产 `backend/app/templates/decoration_knowledge_tree.md` 入库（已复制）
- [x] 2.2 实现 Markdown 解析器（`## 知识目录` 起、缩进层级、`名称 — 描述`）并单测：149 节点、层级与描述正确
- [x] 2.3 创建项目（decoration 模板）时事务内批量生成完整树

## 3. 项目与节点 API

- [x] 3.1 项目 CRUD：GET/POST /api/projects、PATCH/DELETE /api/projects/{id}（经 get_current_workspace 隔离）
- [x] 3.2 树读取：GET /api/projects/{id}/tree（嵌套、按 position 排序）
- [x] 3.3 节点 CRUD：POST /api/projects/{id}/nodes、PATCH/DELETE /api/projects/{id}/nodes/{node_id}
- [x] 3.4 同级排序：POST /api/projects/{id}/nodes/reorder（顺序持久化）
- [x] 3.5 pytest：跨用户项目不可见、模板种子 149 节点、节点 CRUD、级联删除、排序持久化

## 4. 前端

- [x] 4.1 API 客户端扩展（项目/树/节点/排序）
- [x] 4.2 项目管理页：列表、新建（模板选择）、重命名、删除
- [x] 4.3 项目页 NodeTree 真组件：展开/折叠、创建/重命名/删除、原生拖拽 + 上下移排序
- [x] 4.4 路由 `/projects`、`/projects/:id` 接入 ProtectedRoute；冒烟测试（页面渲染、树交互无报错）

## 5. 验证与收尾

- [x] 5.1 联调：注册 → 自动装修项目 → 展开树 → 增删改节点 → 排序 → 删除项目
- [x] 5.2 后端 pytest + ruff、前端 test + lint + build 全绿；390px 可用
- [x] 5.3 `openspec validate --all --strict` 通过 → archive 同步主规格
- [x] 5.4 在 `codex/add-projects` 分支本地提交（不推送，等待用户验证确认后再推送/合并）
