## 1. 后端：Entry 读取新增 subtree 范围

- [x] 1.1 `backend/app/services/entry.py` 的 `list_entries_by_node` 支持 `scope="subtree"`：节点 id 集合为本节点加全部严格后代，复用 `_descendant_node_ids` 实现
- [x] 1.2 更新按节点读取 Entry 的接口校验与文档注释（`backend/app/api/projects.py` 的 `entries` 端点），`scope` 接受 `direct | descendants | subtree`
- [x] 1.3 新增或补充后端测试：`subtree` 返回本节点直接 Entry 与严格后代直接 Entry、不含无关节点，越权项目返回 404
- [x] 1.4 运行后端相关测试（`bash scripts/backend-test.sh` 或等价命令）确认通过

## 2. 前端基础：视图、入口与无壳

- [x] 2.1 `frontend/src/lib/api.ts` 的 `fetchNodeEntries` 与 `frontend/src/lib/queryKeys.ts` 的 `nodeEntries` scope 类型扩展为 `direct | descendants | subtree`
- [x] 2.2 `frontend/src/components/layout/AppShell.tsx` 在 `view=mindmap` 时不渲染左侧 `<aside>`，网格切换为单栏；其他视图行为不变
- [x] 2.3 `frontend/src/pages/ProjectPage.tsx` 增加 `view=mindmap` 分支，渲染思维导图视图；知识空间页头与项目首页目录入口区域增加「思维导图」入口
- [x] 2.4 极简阅读栏：返回知识空间（`?view=directory`）、项目名、阅读侧栏开关；返回后应用壳侧栏恢复
- [x] 2.5 运行前端相关测试（`npm run test:run`）并修复既有回归

## 3. 画布：布局、计数与交互

- [x] 3.1 新增思维导图画布组件：基于 `fetchProjectTree` 数据实现左→右分层树布局，父节点垂直居中于子节点，连线用 SVG 绘制，节点为可点击 button
- [x] 3.2 节点徽标显示「直接数 / 子树数」，子树数前端由嵌套树递归计算（本节点 + 严格后代）
- [x] 3.3 工具栏实现全局展开、全部收起与聚焦子树（临时根 + 面包屑返回项目根）
- [x] 3.4 展开上限：可见节点超限时提示「还有 N 个节点未显示，聚焦子树后查看」
- [x] 3.5 搜索并高亮：按节点名称大小写不敏感子串匹配、`%`/`_` 字面转义，命中高亮、自动展开祖先、无命中提示
- [x] 3.6 空目录、加载中、加载失败重试等状态显式处理
- [x] 3.7 为画布组件补充组件测试：布局计数、展开/收起、聚焦、搜索高亮与空态

## 4. 阅读侧栏

- [x] 4.1 新增阅读侧栏：点击节点后展示该节点知识列表（标题 + 目录路径），「包含子树」默认勾选并显示范围总数
- [x] 4.2 勾选/取消「包含子树」时以 `scope=subtree` 或 `scope=direct` 重新请求 `fetchNodeEntries`
- [x] 4.3 点击条目打开 Entry 详情弹窗（复用 AI 阅读的 `EntryPreviewDialog` 模式）
- [x] 4.4 顶栏侧栏开关可折叠侧栏为纯画布；节点无知识时显示真实空态
- [x] 4.5 为阅读侧栏补充组件测试：范围切换请求、默认勾选、详情打开与空态

## 5. 阅读与管理衔接

- [x] 5.1 思维导图提供「在知识空间中打开」：跳转 `?view=directory&node=<id>`
- [x] 5.2 知识空间目录浏览支持读取 `node` 参数并选中对应节点（含默认回落第一个根节点）
- [x] 5.3 画布与侧栏不出现任何节点管理入口或 AI 拓展入口（代码层面约束 + 测试断言）

## 6. 验证与提交

- [x] 6.1 运行后端测试、前端 `npm run test:run`、`npm run build` 全部通过；`npm run lint` 无本 change 新增问题（`DirectoryDraftDialog` 的 react-hooks 报错为既有问题，主分支已存在，与本 change 无关）
- [ ] 6.2 手工走查：从项目首页与知识空间进入思维导图、无壳全宽、展开/收起/聚焦/搜索高亮、侧栏范围与详情、返回知识空间并定位节点
- [ ] 6.3 按 grove-ui-conventions 视觉流程在 1280 / 1440 / 1600 对照原型截图验收，记录与原型的有意偏离
- [ ] 6.4 执行 `openspec validate --all --strict` 通过后归档 change（`openspec archive add-directory-mind-map-view`），同步主规格
- [ ] 6.5 本地提交（Conventional Commits 中文信息）；不 push、不 merge，等待用户确认
