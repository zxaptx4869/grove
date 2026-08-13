## 1. 骨架与数据迁移

- [x] 1.1 为 Project 增加可空 description 与 active/paused/completed/archived status 字段，创建 Alembic 迁移并保留历史 template 数据；运行 `cd backend && alembic upgrade head`。
- [x] 1.2 更新项目 schema/API：创建默认空目录、列表 status 筛选、状态变更与归档恢复；补齐 Workspace 隔离、生命周期和迁移测试。
- [x] 1.3 扩展节点更新 API 支持 parent_id 移动，拒绝跨项目、自身和后代目标，并补齐位置压紧测试。

## 2. 前端基础体验实现

- [x] 2.1 重建应用路由与 AppShell：登录/注册/退出、全局导航、未实现入口状态，以及 1024px 小屏阻断且不挂载业务 Query。
- [x] 2.2 重建登录注册页与认证错误/loading/disabled 状态，接入现有真实会话 API。
- [x] 2.3 重建项目列表：状态分段筛选、真实查询、loading/empty/error/retry、新建项目表单和删除/归档确认。
- [x] 2.4 重建项目工作台：项目说明与状态、目录树空状态、手动创建/编辑/移动/排序/删除、目录删除确认，以及“与 AI 共创目录”未实现入口。
- [x] 2.5 按 1280px、1440px、1600px 视口调整 Tailwind/shadcn/Lucide 视觉与可访问性，移除旧模板 UI 和移动端业务重排。

## 3. 验证与交付

- [x] 3.1 运行 `cd backend && pytest` 与 `ruff check app tests`，修复全部失败。
- [x] 3.2 运行 `cd frontend && npm test -- --run && npm run lint && npm run build`。
- [x] 3.3 使用浏览器检查 1280px、1440px、1600px，以及 1023px/1024px 边界；对照原型截图并记录有意偏离。
- [x] 3.4 运行 `openspec validate --all --strict`，完成 specs 同步、`openspec archive rebuild-product-foundation-experience`，确认工作区后创建中文 Conventional Commit。
