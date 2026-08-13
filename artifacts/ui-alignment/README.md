# 产品基础体验 UI 对照验收

本目录记录 `align-foundation-ui-with-prototype` Change 的浏览器验收证据。正式页面使用本地专用 Workspace 的真实后端数据，未使用静态假数据。

## 截图矩阵

| 视口 | 正式项目列表 | 正式项目工作台 | 原型项目列表 | 原型项目首页 |
| --- | --- | --- | --- | --- |
| 1280×900 | `actual-projects-1280.png` | `actual-project-workbench-1280.png` | `prototype-projects-1280.png` | `prototype-project-home-1280.png` |
| 1440×900 | `actual-projects-1440.png` | `actual-project-workbench-1440.png` | `prototype-projects-1440.png` | `prototype-project-home-1440.png` |
| 1600×900 | `actual-projects-1600.png` | `actual-project-workbench-1600.png` | `prototype-projects-1600.png` | `prototype-project-home-1600.png` |

端侧边界：

- `boundary-1023.png`：仅显示电脑访问提示，不加载业务工作台。
- `boundary-1024.png`：完整加载项目工作台，无横向滚动、遮挡或文字溢出。

## 对照结论

采用了原型的紧凑左侧应用壳、项目上下文侧栏、短标题区、四段项目状态、密集列表行、项目主内容与右侧状态区，以及知识目录的树/详情两栏结构。账户与低频操作统一收进菜单，破坏性操作使用确认对话框。

## 有意偏离

- 原型项目首页的待确认候选、最近正式知识、AI 项目理解和快捷采集不属于本轮范围，正式页不创建占位区或伪造统计，主内容改为真实目录工作台。
- 原型项目列表中的正式知识数、候选数和最近更新时间没有当前接口支持，正式页只展示真实的目标与背景、目录节点数和生命周期状态。
- 原型含收集箱、搜索、确认台、知识空间、AI 阅读等后续能力；正式全局壳只保留本轮需要的项目入口，收集箱与搜索以明确 disabled 状态呈现，不创建占位页面。
- “与 AI 共创目录”保留可点击入口并说明能力边界，但不会生成或修改目录，因为 Directory Agent 不在本轮实现范围内。
- 正式页面使用 React 19、Tailwind 4、shadcn/ui 与 Lucide 重建，没有复制原型 HTML 或内联样式。
