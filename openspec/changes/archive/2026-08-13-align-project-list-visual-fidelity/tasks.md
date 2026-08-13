## 1. 视觉骨架

- [x] 1.1 校准 `frontend/src/index.css` 的 Grove 基础颜色、字体栈、字号、行高与圆角令牌，并通过 `npm run build` 确认 Tailwind 令牌可用
- [x] 1.2 重写 `AppShell` 的 216/184px 侧栏、52px 品牌栏与主顶栏、表面层级和全宽内容容器，并通过浏览器计算样式确认关键尺寸

## 2. 项目列表实现

- [x] 2.1 重写 `ProjectsPage` 标题区、状态筛选和稳定 loading/empty/error 区域，使页面使用 22px/24px/30px 内边距与原型相同的内容流
- [x] 2.2 对齐项目行的 66px 行高、34px 图标、真实次要信息、22px 状态标识、34px“进入项目”链接和低权重更多菜单
- [x] 2.3 更新项目列表测试，覆盖真实字段、直接进入链接、四状态筛选以及未渲染原型静态统计

## 3. 自动化验证

- [x] 3.1 在 `frontend/` 执行 `npm test -- --run`、`npm run lint` 和 `npm run build`
- [x] 3.2 在仓库根目录执行 `openspec validate --all --strict`，确认 Change 与主规格严格有效

## 4. 浏览器视觉验收

- [x] 4.1 在 1280×800、1440×900、1600×900 截取正式项目列表，对照原型核对侧栏、顶栏、内容边界、背景、字体、间距和控件尺寸，并将截图与结果记录到 `design.md`
- [x] 4.2 在 1023px 验证只显示电脑访问提示，在 1024px 验证完整应用壳可用且无业务控件溢出
- [x] 4.3 复核 loading、empty、error、disabled、删除确认和键盘可达状态，记录未实现功能导致的有意偏离

## 5. 规格与交付

- [x] 5.1 将 delta specs 同步到 `frontend-foundation`、`product-shell` 和 `project-management` 主规格并再次严格校验
- [x] 5.2 归档 `align-project-list-visual-fidelity` Change，检查工作树后以中文 Conventional Commit 提交到当前本地 `codex/` 分支
