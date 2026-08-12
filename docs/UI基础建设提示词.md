# 知林 Grove — UI 基础建设提示词

你是知林 Grove 项目的主程。Grove 是「个人知识管家」Web 产品（产品提案见 PROPOSAL.md，技术选型已确认：React 19 + TypeScript + Vite + Tailwind 4 + shadcn/ui + TanStack Query）。本次任务只做两块 **UI 基础建设**，不实现业务功能：

1. 创建仓库级 Codex 技能 `grove-ui-conventions`
2. 安装并集成第一批基础组件

## 开始前

- 完整阅读 PROPOSAL.md、README.md、AGENTS.md，并查看 frontend 现状（src 结构与 index.css）
- 全程用中文沟通与代码注释
- 新建分支 codex/ui-foundation，所有提交都在该分支

## 任务一：创建 grove-ui-conventions 技能

目标：让 grove 项目里任何未来的 Codex 会话都能自动遵守统一的 UI 规范。

- 位置：`.codex/skills/grove-ui-conventions/SKILL.md`（仓库级技能）
- 若环境提供 skill-creator 技能，按它的流程创建并校验；若不可用，手动创建并确保 SKILL.md 格式正确（frontmatter 含 name/description，内容中文）
- SKILL.md 必须包含：
  1. **设计令牌**：色板（主色 + 语义色：AI 候选、正式记录、风险、成功、警告、错误）、字号阶梯、间距、圆角、阴影、动效时长；**以 frontend 实际的 Tailwind 4 @theme 文件为准**（例如 src/index.css 或 src/theme.css），文档只做摘要，防止漂移
  2. **产品组件清单**：采集入口（DropZone）、候选卡片 CandidateCard、确认栏 ConfirmBar、目录树 NodeTree、来源面板 SourcePanel、任务状态组件、空状态、对话面板（Phase 2 插槽，数据驱动、可被生成式 UI 替换）
  3. **交互状态规范**：loading / empty / error / partial / undo 每类状态的要求
  4. **文案规则**：区分「AI 建议/候选」与「正式记录」的措辞
  5. **验收清单**：桌面 + 390px 双轨、键盘可达/焦点态/对比度、组件数据驱动可替换

## 任务二：安装并集成第一批基础组件

- 在 frontend 下安装：`react-dropzone`、`sonner`、`react-hook-form`、`zod`、`@hookform/resolvers`、`@tanstack/react-table`、`cmdk`、`react-markdown`
- 用 shadcn CLI 补充官方组件（如 command、table、form、sonner、dialog、textarea、badge、separator 等），保持 components.json 与现有 ui/ 目录风格一致
- 集成要求：
  1. Sonner 的 Toaster 挂到应用根部，主题跟随设计令牌
  2. 新增依赖只做基座接入与示例，不写真实业务流程
  3. 目录约定：`src/components/ui/`（shadcn 生成）、`src/components/features/`（产品组件占位）、`src/lib/`、`src/pages/`
  4. 设计令牌落到 Tailwind 4 @theme（如尚未建立，本次建立 src/index.css 或 src/theme.css）
- 为新增基座补 1-2 个冒烟测试（组件可渲染、无报错）

## 验收标准

1. `.codex/skills/grove-ui-conventions/SKILL.md` 存在且内容完整（含上面 5 部分）
2. 依赖安装成功；`npm test -- --run`、`npm run lint`、`npm run build` 全通过
3. 新增组件能在 dev server 正常渲染（可在浏览器验证桌面与 390px）
4. 未实现任何业务功能（不写采集/确认/目录逻辑）
5. 提交并推送 codex/ui-foundation 到远端

## 约束

- 不接入 CopilotKit、不接真实 AI、不做移动端
- 不复制 KnowStruct 业务代码，可参考其工程模式
- 组件保持数据驱动、可替换，为 Phase 2 生成式 UI 留口
- 遇到分歧先记录决策，不静默猜测
