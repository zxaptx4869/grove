---
name: grove-ui-conventions
description: 知林 Grove 产品前端实现与验收规范。Use when implementing, adjusting, prototyping, or reviewing Grove pages and React components; handling AI candidates, confirmation, entries, sources, directory trees, task states, search, or AI reading; or validating desktop workbench layouts, small-screen boundaries, accessibility, copy, and interaction states with Tailwind 4 and shadcn/ui.
---

# Grove UI 实现规范

## 权威来源

开始前按任务范围读取：

1. `docs/产品蓝图.md`：先确认稳定基线和任务路由。
2. 索引路由到的 1 至 2 份产品专题：只读取当前页面和交互需要的详细决策。
3. 当前 OpenSpec change 与 `openspec/specs/`：本次必须实现和明确不做的行为。
4. `frontend/src/index.css`：颜色、字号、圆角、阴影和动效令牌。
5. 相关页面与组件代码：现有接口和交互模式。
6. `docs/prototypes/README.md` 与对应原型页面：仅在当前 change 涉及的页面需要视觉或信息层级参考时读取。

常见 UI 任务路由：

- 采集、Candidate、确认台和 Source 任务：`核心对象与关系.md` + `采集整理与确认.md`。
- Entry、目录、知识空间、搜索和 AI 阅读：`核心对象与关系.md` + `目录与知识空间.md`。
- 目录 Agent 或其他 AI 行为：`目录与知识空间.md` + `Agent架构与AI边界.md`。
- 桌面布局和小屏边界：`技术与端侧边界.md`，必要时再读页面所属专题。

除跨页面产品审计或调整蓝图结构外，不读取全部产品专题。

冲突时依次遵循 OpenSpec、相关产品专题、实际主题和现有代码。不要在本 skill 维护第二套产品决策、组件 API 或令牌值；修改主题后再检查本 skill 是否仍准确。

原型只提供视觉与交互参考，不证明功能已经实现。正式开发使用现有 React、Tailwind 4、shadcn/ui 和 Lucide 重新实现，不复制原型的内联样式、包装 iframe、演示脚本或静态业务状态；有意偏离项记录到当前 change 的 `design.md`。

## 实施方式

- 先画清页面状态和用户主任务，再选择现有 shadcn/ui 与 Lucide 组件。
- 延续现有布局和组件模式；只有真实复用出现时才提取产品组件，不预建未来占位组件。
- 产品组件保持数据驱动，但不要为了“可替换”制造无业务价值的抽象。
- 页面首屏直接服务工作流，不做营销式 Hero、装饰性统计卡或卡片套卡片。
- 将 Web 作为桌面知识整理工作台，从 1024px 视口宽度开始支持完整流程，重点优化 1280px、1440px 和 1600px。
- 低于 1024px 时不把桌面工作台重排为手机业务界面；统一显示电脑访问提示，不提供继续访问或部分功能入口。
- 原生 App 上线后，小屏承接页才改为打开或下载 App；不要在 Web 页面中提前实现 App 业务流程。

## 产品语义

- **AI Candidate**：始终标识为“AI 候选”“AI 建议”或“待确认”；不得使用“已归档”“正式记录”等文案。可使用 `ai-candidate` 语义色，但不能只靠颜色区分。
- **Entry**：使用“已确认”“正式知识”等明确措辞，并提供到 Source 证据的可达入口。正式状态可使用 `confirmed` 语义色。
- **人工决定**：AI 推荐的内容、类型、项目和目录可以预填，但按钮与结果必须表达这是用户确认。确认决定作用于 Candidate，Source 只负责分组和上下文。
- **推荐状态**：使用“推荐明确”“需要确认”“暂无合适位置”等可解释状态，不展示模型自报的伪精确百分比。
- **来源**：精审时证据与 Candidate 保持可见或一键可达；列表和批量视图至少显示来源标识并能展开原文。
- **目录**：目录树是用户心智模型。AI 新增、改名、移动或删除只能呈现为草稿/建议；删除必须显示受影响内容。

## 关键交互

- 按 Source 审阅：显示 Source 列表、原始材料/证据和当前 Source 的 Candidate；全部 Candidate 有决定后才将 Source 标记为已处理。
- 批量处理：按 Candidate 平铺或按推荐目录分组；冲突、重复、证据不足和高风险项退出批量快审。
- 一次确认可接受当前 Candidate 内容、类型、项目和目录；仅在推荐不明确时增加操作。
- “新增节点并归档”明确展示新节点路径，并作为单次原子操作表达。
- 卡片与列表是同一 Entry 数据的两种视图；卡片服务阅读，列表服务扫描、筛选与批量管理。
- 思维导图默认只画目录节点，Entry 在节点侧栏展示，避免将知识全部铺进图中。

## 状态与反馈

每个数据区域显式处理 loading、empty、error、partial、retry 和 disabled；破坏性操作提供撤销或二次确认。

- loading：保留稳定尺寸，避免空白闪烁和布局跳动。
- empty：说明当前状态并提供一个最相关动作，不堆叠多个主按钮。
- error：说明问题和下一步，不展示堆栈；任务失败允许从失败步骤重试。
- partial：逐项显示成功与失败，只重试失败项。
- toast 只反馈短暂结果；需要用户处理的错误保留在对应内容附近。

## 视觉与可访问性

- 使用 `frontend/src/index.css` 的 Tailwind 语义令牌，避免硬编码业务颜色和魔法值。
- 正文对比度至少 4.5:1；状态同时使用文字、图标或边框表达。
- 按钮使用 Lucide 图标；不熟悉的纯图标按钮提供 `aria-label`、`title` 或 Tooltip。
- 保证键盘顺序、可见 `focus-visible`、对话框焦点归还、拖拽入口的文件选择替代方案。
- 固定格式元素使用稳定尺寸与响应式约束；动态文字、徽标和加载态不能导致工具栏或列表跳动。
- 避免过度圆角、单一紫色主题、渐变装饰和无功能的大面积留白。

## 验收

完成前至少检查：

1. 在 1280px、1440px 和 1600px 检查桌面主流程，无非预期横向滚动、遮挡或文字溢出；窄桌面窗口与浏览器缩放仍应有清晰反馈。
2. 若当前 change 包含端侧边界实现，检查低于 1024px 的访问不会进入业务工作台；阻断页实现前不得宣称手机 Web 可用。
3. Candidate、Entry、Source 和 AI 推荐在文案与操作上没有混淆。
4. loading、empty、error、partial、retry 和破坏性操作状态完整。
5. 键盘、焦点、对比度和图标标签可用。
6. 运行相关前端测试、`npm run lint` 和 `npm run build`；关键界面通过浏览器截图检查。
7. 若当前 change 对应产品原型页面，在 1280px、1440px 和 1600px 对照原型检查，并确认只实现了本次规格范围内的行为。
