## 1. 变更工件与基线

- [x] 1.1 运行 `openspec validate --all --strict`，确认本 change 四个工件校验通过
- [x] 1.2 确认分支为 `codex/add-hierarchical-directory-selector`，工作区无无关改动

## 2. 基础组件

- [x] 2.1 新增 `ui/popover.tsx`（基于 radix-ui）
- [x] 2.2 新增 `DirectoryTreeSelect`：树形浏览、展开/收起、选中路径展示
- [x] 2.3 支持搜索（名称 + 完整路径）、自动展开祖先、直接 Entry 数展示
- [x] 2.4 支持 `allowRoot`、`filter`、`loading` 与空目录状态

## 3. 三处接入

- [x] 3.1 确认台归档目录替换为 `DirectoryTreeSelect`
- [x] 3.2 批量「修改目录」弹窗替换为 `DirectoryTreeSelect`
- [x] 3.3 移动节点弹窗替换为 `DirectoryTreeSelect`（排除自身/后代，允许根目录）

## 4. 测试与构建

- [x] 4.1 新增 `DirectoryTreeSelect` 测试：展开、选择、搜索、根目录、Entry 数
- [x] 4.2 更新 `ReviewPage` 目录选择相关测试
- [x] 4.3 运行 `cd frontend && npm run test:run`
- [x] 4.4 运行 `cd frontend && npm run lint`
- [x] 4.5 运行 `cd frontend && npm run build`

## 5. 收尾

- [x] 5.1 再次运行 `openspec validate --all --strict`
- [x] 5.2 运行 `openspec archive add-hierarchical-directory-selector`
- [x] 5.3 本地中文 Conventional Commit，不 push、不 merge，等待用户确认
