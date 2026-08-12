---
name: grove-ui-conventions
description: 知林 Grove 前端 UI 规范（设计令牌、产品组件清单、交互状态、文案、验收清单）。Use when implementing or adjusting Grove frontend UI, building React components with Tailwind 4 / shadcn/ui, adding product components (采集入口、候选卡片、确认栏、目录树、来源面板、任务状态、空状态、对话面板), checking mobile 390px layout, or reviewing accessibility/state handling in grove frontend code.
---

# 知林 Grove UI 规范

本技能是 Grove 前端 UI 的统一约束。权威来源是前端代码本身：**设计令牌以 `frontend/src/index.css`（Tailwind 4 @theme）为准**，本文档只做摘要；改动令牌必须先改 `frontend/src/index.css`，再同步本摘要，防止漂移。

## 1. 设计令牌摘要

权威文件：`frontend/src/index.css`。所有颜色、字号、间距、圆角、阴影、动效时长一律使用 @theme 令牌，禁止硬编码魔法值。

### 色板（语义色）

| 令牌 | 用途 | 说明 |
|---|---|---|
| `primary` / `primary-foreground` | 主色（品牌/主操作） | slate 深色系 |
| `ai-candidate` / `ai-candidate-soft` | AI 候选、建议、未确认内容 | violet 系，配 `bg-ai-candidate-soft` 底色 + `text-ai-candidate` |
| `confirmed` / `confirmed-soft` | 正式记录（Entry） | teal/emerald 系，表示已确认、可追溯 |
| `risk` / `risk-soft` | 风险提示（置信度低、字段缺失） | amber 系 |
| `success` / `success-soft` | 成功反馈 | green 系 |
| `warning` / `warning-soft` | 警告（非阻塞） | yellow 系 |
| `error` / `error-soft` | 错误（阻塞） | red 系，与 `destructive` 语义一致 |

用法示例：候选卡片用 `border-ai-candidate/40 bg-ai-candidate-soft/40`；正式记录标签用 `bg-confirmed-soft text-confirmed`。

### 字号阶梯

`--text-caption`(12px) → `--text-body-sm`(13px) → `--text-body`(14px) → `--text-title`(16px) → `--text-heading`(20px) → `--text-display`(24px)。正文用 `text-body`，页面标题用 `text-heading` 起；小屏（390px）标题可降一档。

### 间距

以 Tailwind 默认 `--spacing: 0.25rem` 4px 基准：`gap-1`=4px … `gap-4`=16px，块级间距常用 16/24/32px（`space-y-4/6/8`）。卡片内边距统一 `p-4` 或 `p-5`。

### 圆角

`--radius` 基值 0.625rem；层级 `rounded-sm/md/lg/xl`（@theme inline 已映射）。按钮/输入框用 `rounded-md`，卡片用 `rounded-lg`，对话框用 `rounded-xl`。

### 阴影

默认 `shadow-xs/sm/md`；新增 `shadow-card`（卡片常态）、`shadow-pop`（浮层/弹层）两个语义令牌，弹层不得使用默认 `shadow` 之外的深阴影。

### 动效时长

`--transition-duration-fast`(120ms)、`--transition-duration-base`(200ms)、`--transition-duration-slow`(300ms)，对应 `duration-fast/base/slow` 工具类。微交互（hover）用 fast，面板展开/消失用 base/slow；尊重 `prefers-reduced-motion`。

## 2. 产品组件清单

产品组件放在 `frontend/src/components/features/`，**全部数据驱动、可替换**：只接受 props/数据，不内嵌业务调用；为 Phase 2 生成式 UI 预留（组件可被同接口的生成版本整体替换）。

| 组件 | 职责 | 数据驱动要求 |
|---|---|---|
| `DropZone` 采集入口 | 拖拽/粘贴/上传入口 | 接收 `onFiles` 回调与 `accept` 配置；本身不管理业务状态 |
| `CandidateCard` 候选卡片 | 展示 AI 候选（标题/内容/目录建议/置信度） | 接收 `Candidate` 数据与 `onConfirm/onReject/onEdit`；必须带「AI 候选」标识 |
| `ConfirmBar` 确认栏 | 批量采纳/逐条处理的操作栏 | 接收选中数量与批量动作回调 |
| `NodeTree` 目录树 | 项目目录树展示与选择 | 接收 `Node[]` 与选中/展开状态；纯受控组件 |
| `SourcePanel` 来源面板 | 展示 Entry 的来源材料与溯源 | 接收 `Source[]`；只读展示 |
| `TaskStatus` 任务状态 | ProcessingTask 状态徽标（PENDING/RUNNING/FAILED/SUCCESS） | 接收 `status` 枚举映射为徽标样式；失败态可附带重试回调 |
| `EmptyState` 空状态 | 采集箱/目录/搜索结果为空时的引导 | 接收 `title/description/action` |
| `ConversationPanel` 对话面板 | Phase 2 插槽：问答/共创界面 | 本阶段只留占位，数据驱动（`messages` props），后续可整体替换为生成式 UI |

## 3. 交互状态规范

每个列表/页面级组件必须显式处理以下状态，不得缺失：

- **loading**：骨架屏或居中 spinner；禁止空白闪烁；加载中禁用相关操作按钮。
- **empty**：使用 `EmptyState` 给出可行动作，而不是一句「暂无数据」。
- **error**：错误信息面向用户可理解（含重试按钮），不展示堆栈；区分「网络失败」与「任务失败」。
- **partial**：部分成功/部分失败（如批量采纳中有失败项）时，逐条标注成功与失败，并允许用户只重试失败项。
- **undo**：破坏性/批量操作（拒绝候选、删除）必须可撤销或需二次确认；撤销窗口期显示提示条（可放 sonner Toaster，duration 4s）。

## 4. 文案规则

- **AI 候选**：用「AI 建议」「候选」「待确认」；不得用「已保存」「已归档」等暗示正式性的措辞。CandidateCard 必须显式标注。
- **正式记录**：用「已确认」「正式记录」「已归档」；展示时必须能与候选区分（视觉 + 措辞双通道）。
- **确认动作**：动词统一「采纳 / 拒绝 / 微调」，批量场景用「批量采纳」。
- **置信度**：用「置信度：高/中/低」，不用百分比伪精确（除非产品定义明确）。
- 所有文案中文优先；错误提示以「问题 + 建议动作」结构编写。

## 5. 验收清单

任何 UI 改动合入前逐项检查：

1. **双轨适配**：桌面（≥1024px）与 390px 移动宽度均无横向滚动，主要操作在 390px 下可完成。
2. **键盘可达**：Tab 顺序合理、焦点态可见（`focus-visible` ring）、对话框可 Esc 关闭并归还焦点；拖拽组件提供键盘替代入口（点击选择文件）。
3. **对比度**：正文与背景对比度 ≥4.5:1；语义色（如 `text-ai-candidate`）同时配 soft 背景，不单靠颜色传达状态。
4. **数据驱动可替换**：组件 props 接口清晰，无隐式全局状态；Phase 2 候选插槽组件可整体替换。
5. **状态完整**：loading/empty/error/partial/undo 均有处理；`npm test -- --run`、`npm run lint`、`npm run build` 通过。
