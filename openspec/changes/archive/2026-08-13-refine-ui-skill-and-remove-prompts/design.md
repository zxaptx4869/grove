## Context

两份提示词分别用于初始化工程和 UI 基座，其任务已经完成，结果可由归档 change、主规格、代码和 README 追溯。`grove-ui-conventions` 是仓库级 skill，会在 Grove 前端任务中自动加载，适合承载通用模型无法从组件代码稳定推导出的产品语义与验收规则；但现有版本仍按早期提案组织，列出多项不存在的组件并包含已失效的阶段表述。

## Goals / Non-Goals

**Goals:**

- 删除不再作为当前输入的一次性提示词。
- 保留一个简洁、可触发、与产品蓝图一致的 Grove UI skill。
- 明确 skill、产品蓝图、实际 CSS 和现有组件之间的权威顺序。
- 把 AI 候选、正式 Entry、来源证据、确认台双视图和响应式验收固化为可重复执行的前端规则。

**Non-Goals:**

- 不让 skill 成为组件 API 或设计令牌的第二份事实来源。
- 不要求预先创建未来组件。
- 不修改前端运行时代码和视觉主题。

## Decisions

### D1：保留 skill，而不是合并进普通文档

skill 的价值在于触发机制：实施或调整 Grove 前端时自动加载，减少每个 change 重复说明产品语义。普通蓝图负责“做什么”，skill 负责“前端任务如何读取上下文、落地和验收”。

### D2：权威顺序明确化

产品行为和优先级以产品蓝图与 OpenSpec 为准；设计令牌以 `frontend/src/index.css` 为准；现有组件接口以代码为准；skill 只记录工作流和跨页面不变量。若发生冲突，先修正权威来源，再同步 skill 摘要。

### D3：删除固定组件清单，改为按能力读取

不再声称 CandidateCard、ConfirmBar、SourcePanel 等组件必须已经存在，也不固定未来 props。每次 change 先读取相关页面、现有组件和规格；只有真实复用出现时才提取组件。

### D4：保留产品专属的 UI 不变量

- Candidate 与 Entry 在文案、颜色和操作上明确区分；
- Source 证据始终可达；
- 确认决定作用于 Candidate，Source 只分组；
- AI 推荐可预填但不得伪装成用户决定；
- loading、empty、error、partial、retry、undo/confirm 状态完整；
- 桌面与 390px 的关键流程均可完成。

## Risks / Trade-offs

- [skill 与代码再次漂移] → 只摘要稳定不变量，令牌与接口明确指向代码，每次相关 change 同步检查。
- [规则过多抑制页面设计] → 删除固定布局和组件 API，只保留产品铁律、状态与验收底线。
- [删除任务书损失历史] → 归档 change 和 Git 历史已覆盖实施原因与结果。
