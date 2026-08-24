## 1. OpenSpec 工件

- [x] 1.1 创建 change `refine-sidebar-project-status-icon` 并编写 proposal / specs / design / tasks
- [x] 1.2 `openspec validate --all --strict` 通过

## 2. 前端实现

- [x] 2.1 `AppShell.tsx`：新增状态图标映射（CircleDot / Pause / CircleCheck / Archive + 语义色），切换按钮改单行（状态图标 + 项目名 + 箭头），容器间距 `mb-2`；下拉项目项加状态图标、当前项目选中勾移至右侧
- [x] 2.2 更新 AppShell 测试：状态图标断言（role=img + 可访问名称）、单行按钮与间距回归、下拉分组与选中态保持

## 3. 验证与收尾

- [x] 3.1 `npm run lint`、`npm run test`、`npm run build` 通过
- [x] 3.2 `openspec validate --all --strict` 通过后归档同步主规格
- [x] 3.3 本地提交（不 push、不 merge）
