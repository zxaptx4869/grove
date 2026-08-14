## Why

Organizing Agent 已经把 Source 变成只读候选，但用户还没有地方逐条决定是否采纳。可信整理闭环要求人在环上：候选必须由用户采纳或拒绝，Source 才能算处理完成。本 change 在项目内落地「确认台」，让用户按 Source 审阅候选。

## What Changes

- 新增 `candidate-review` 能力：
  - Candidate 状态机：待采纳 / 已采纳 / 已拒绝；
  - 用户可编辑候选后采纳，可拒绝，可在当前 Source 内多选批量采纳/拒绝；
  - 「跳过」不改变状态，仅作为前端导航动作；
  - 按 Source 审阅工作台，展示当前项目内待审 Source、原始材料与候选。
- 修改 `source-management` 能力：
  - Source 新增 `review_status`，派生为待确认 / 部分确认 / 已处理。

## Capabilities

### New Capabilities

- `candidate-review`: Candidate 决策状态与编辑、按 Source 审阅、Source 内批量决策。

### Modified Capabilities

- `source-management`: Source 新增审阅状态，与处理状态分离。

## Impact

- 后端：Candidate 决策 API、Source 审阅状态派生、Source 列表返回审阅状态。
- 前端：项目导航新增「确认台」，新增按 Source 审阅页面与候选操作。
- 无新外部依赖；复用现有 Source/Candidate/Attachment。

## Non-Goals

- 不做 Entry 与来源证据关系。
- 不做目录节点推荐与确认归档。
- 不做跨 Source 批量处理视图（后续 `add-batch-candidate-review`）。
- 不做 AI 项目推荐或确认台内修改 Source 项目。
- 不做暂缓状态（用「跳过」替代）。
