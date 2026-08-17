## 1. 变更工件与基线

- [x] 1.1 运行 `openspec validate --all --strict`，确认本 change 四个工件校验通过
- [x] 1.2 确认分支为 `codex/add-project-global-nav-entries`，工作区无无关改动

## 2. 前端实现

- [x] 2.1 在 `AppShell` 的 `ProjectNavigation` 项目导航后增加分隔线
- [x] 2.2 增加「收集箱」（`/inbox`）与「搜索」（`/search`）两个 `NavLink`，沿用全局导航样式与激活态
- [x] 2.3 确认项目侧栏不重复「账户」入口

## 3. 测试与验证

- [x] 3.1 运行 `cd frontend && npm run test:run`
- [x] 3.2 运行 `cd frontend && npm run lint`
- [x] 3.3 运行 `cd frontend && npm run build`
- [x] 3.4 在 1280px、1440px、1600px 检查项目侧栏无溢出、遮挡或激活态异常（代码与构建层面；浏览器截图由用户最终确认）

## 4. 收尾

- [x] 4.1 再次运行 `openspec validate --all --strict`
- [x] 4.2 运行 `openspec archive add-project-global-nav-entries`
- [x] 4.3 本地中文 Conventional Commit，不 push、不 merge，等待用户确认
