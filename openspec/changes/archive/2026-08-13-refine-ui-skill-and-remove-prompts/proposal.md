## Why

`docs/初始化提示词.md` 与 `docs/UI基础建设提示词.md` 都是已完成的一次性任务书，继续保留会把旧路径和旧产品阶段暴露给后续代理。仓库级 `grove-ui-conventions` skill 仍能持续约束 Grove 特有的候选/正式记录区分、来源、状态和 390px 体验，但其组件清单与措辞已经落后于当前产品蓝图，需要精简更新而非原样保留。

## What Changes

- 删除两份已完成的一次性提示词文档。
- 保留并重写 `grove-ui-conventions` skill，使其以产品蓝图和实际主题文件为权威来源。
- 移除未实现组件的强制接口、旧 Phase 2 表述、百分比置信度和过时的“采纳/微调”文案。
- 增加确认台双视图、AI 推荐与人工决定、来源证据、项目/目录状态、桌面与 390px 验收等长期规则。
- 使用 skill-creator 校验脚本验证 skill 元数据与目录结构。
- 将仓库级 UI skill 的存在和职责加入 `frontend-foundation` 主规格。

### Non-Goals

- 不修改前端运行时代码、CSS 令牌、页面或组件。
- 不实现产品蓝图中的采集、确认、Entry、目录共创或 AI 阅读功能。
- 不删除已归档 OpenSpec 工件中的历史引用。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `frontend-foundation`: 增加仓库级 Grove UI skill 的权威来源、核心产品语义和验收职责要求。

## Impact

- 删除：`docs/初始化提示词.md`、`docs/UI基础建设提示词.md`。
- 更新：`.codex/skills/grove-ui-conventions/SKILL.md` 及其 `agents/openai.yaml` 元数据。
- 规格：`openspec/specs/frontend-foundation/spec.md` 经 delta spec 同步新增要求。
- 不影响依赖、构建产物、API、数据库和运行时行为。
