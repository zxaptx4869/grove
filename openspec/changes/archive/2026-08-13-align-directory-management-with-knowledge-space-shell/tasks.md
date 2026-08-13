## 1. 知识空间骨架

- [x] 1.1 更新 `AppShell` 项目导航与 `ProjectPage` 项目首页入口，将用户可见的“目录管理”统一为“知识空间”，保留 `?view=directory` URL 和正确激活态；运行 `cd frontend && npm test -- --run src/pages/ProjectPage.test.tsx` 验证入口。
- [x] 1.2 将项目页目录分支重组为原型层级的知识空间标题区、250px 目录树和剩余内容区，并保持 loading、error 与工作区尺寸稳定；运行 `cd frontend && npm test -- --run src/pages/ProjectPage.test.tsx` 验证页面状态。
- [x] 1.3 实现非空目录默认选择第一个根节点、有效选择保留和删除后回退逻辑，并在内容区显示真实路径、节点信息、编辑入口与“暂无正式知识”空态；运行相关页面测试验证节点切换。
- [x] 1.4 保持空目录的“手动创建”和“与 AI 共创目录”两个平等入口，确认页面不显示卡片/列表、思维导图、知识计数、来源或静态 Entry；运行页面测试验证空态与 Non-Goals。

## 2. 目录操作回归

- [x] 2.1 回归 `NodeTree` 根节点创建、子节点创建、编辑、移动、同级排序和删除回调，必要时只调整知识空间布局所需的呈现；运行 `cd frontend && npm test -- --run src/components/features/NodeTree.test.tsx`。
- [x] 2.2 验证目录 mutation 的 disabled、邻近错误、成功 toast、删除二次确认和 AI 未实现说明在知识空间中保持可用；补充 `ProjectPage` 回归测试并运行对应测试文件。
- [x] 2.3 检查纯图标按钮的可访问名称、键盘焦点和动态文本截断，确认目录树与内容工具栏不会因名称或状态变化发生非预期位移；运行 `cd frontend && npm run lint`。

## 3. 视觉与规格验收

- [x] 3.1 在 1440×900 对照知识空间原型完成正式页面截图检查，并读取关键元素计算样式，核对 250px 树栏、604px 最小工作区、树栏/内容区内边距、50px 节点工具栏、字体、颜色、边框和溢出；将证据保存到本 Change 的 `artifacts/`。
- [x] 3.2 在 1280×900 和 1600×900 复核知识空间无横向滚动、遮挡、文字溢出或布局漂移，并记录有意偏离仅为 design 中列出的未实现能力。
- [x] 3.3 运行 `cd frontend && npm test -- --run`、`cd frontend && npm run lint` 和 `cd frontend && npm run build`，确认全部前端验证通过。
- [x] 3.4 在仓库根目录运行 `openspec validate --all --strict`，复核没有静态 Entry、Source、知识计数、思维导图或 Directory Agent 行为进入实现范围。
- [x] 3.5 完成实现后同步规格、归档 Change 并按中文 Conventional Commits 创建本地提交；不 push、不 merge，等待用户体验确认。
