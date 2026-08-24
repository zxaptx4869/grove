## 1. OpenSpec 工件

- [x] 1.1 创建 change `refine-sidebar-project-status-badge` 并编写 proposal / specs / design / tasks
- [x] 1.2 `openspec validate --all --strict` 通过

## 2. 前端实现

- [x] 2.1 `AppShell.tsx`：移除状态图标映射与 `ProjectStatusIcon`，新增状态标签映射（Badge outline + 语义色）；切换按钮恢复两行（项目名 + 状态标签），容器 `mb-2`；下拉项目项恢复「选中勾 + 项目名」，移除状态图标
- [x] 2.2 更新 AppShell 测试：状态标签文字断言、下拉选中勾与分组回归

## 3. 验证与收尾

- [x] 3.1 `npm run lint`、`npm run test`、`npm run build` 通过
- [x] 3.2 `openspec validate --all --strict` 通过后归档同步主规格
- [x] 3.3 本地提交（不 push、不 merge）
