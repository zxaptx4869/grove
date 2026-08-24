## 1. OpenSpec 工件

- [x] 1.1 创建 change `add-sidebar-project-switcher` 并编写 proposal / specs / design / tasks
- [x] 1.2 `openspec validate --all --strict` 通过

## 2. 前端实现

- [x] 2.1 `AppShell.tsx`：`ProjectNavigation` 项目名改为可交互下拉（DropdownMenu + useAllProjects）；按状态分组渲染全部非归档项目、当前项目组内置顶选中；已归档当前项目单列；底部「全部项目」入口；切换时保留视图类型（替换 `/projects/:id` 段）
- [x] 2.2 新增/更新前端测试覆盖分组、选中态、保留视图、已归档单列、非项目页不显示

## 3. 验证与收尾

- [x] 3.1 `npm run lint`、`npm run test`、`npm run build` 通过
- [ ] 3.2 浏览器主视口走查（1280 / 1440 / 1600px）与计算样式核对（本会话浏览器执行面不可用，需用户本地确认）
- [x] 3.3 `openspec validate --all --strict` 通过后归档同步主规格
- [ ] 3.4 本地提交（不 push、不 merge）
