## 1. 视觉骨架与基础组件

- [x] 1.1 根据逐屏对照矩阵补充 Grove surface/sidebar/brand 主题令牌和稳定布局尺寸，运行 `cd frontend && npm run build`。
- [x] 1.2 增加并测试项目/目录操作所需的 shadcn/ui DropdownMenu、Tooltip 等基础组件，不新增业务依赖。
- [x] 1.3 重构认证布局和 AppShell：品牌区、全局导航、真实最近项目、账户菜单、退出确认与未实现入口状态。

## 2. 页面与交互校准

- [x] 2.1 重做登录注册页的表单框架、邻近 API 错误、提交中与可访问性状态。
- [x] 2.2 重做项目列表的标题区、状态 segmented control、紧凑列表行、更多菜单、新建和破坏性确认状态。
- [x] 2.3 重做项目工作台的信息层级、项目状态/背景 section、目录两栏工作区和空目录双入口。
- [x] 2.4 重做目录节点行为：文件夹层级、上下文菜单、添加/编辑/移动/排序/删除和影响确认，去除工程缩写按钮。
- [x] 2.5 更新前端测试，覆盖认证错误、项目状态筛选、行级菜单、空目录入口和目录操作。

## 3. 截图验收与交付

- [x] 3.1 运行 `cd frontend && npm test -- --run && npm run lint && npm run build` 以及后端测试和 ruff，确保真实 API 无回归。
- [x] 3.2 使用专用本地验收数据，在 1280px、1440px、1600px 生成项目列表/项目工作台的原型与正式截图，并写入 `artifacts/ui-alignment/README.md`。
- [x] 3.3 生成 1023px 与 1024px 边界截图，检查横向滚动、遮挡、文字溢出、焦点、disabled、error 和破坏性确认状态。
- [x] 3.4 人工读取全部截图并修复明显偏差；运行 `openspec validate --all --strict` 后同步规格、归档 Change 并创建本地中文 Conventional Commit，不 push、不 merge。
