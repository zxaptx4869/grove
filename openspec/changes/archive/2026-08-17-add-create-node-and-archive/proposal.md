## Why

上一 change 已经把目录推荐推进到三档路由状态，但 `no_suitable`（暂无合适位置）分支仍然断在“手动选已有节点”：当项目目录为空或确实没有匹配节点时，用户无法在一次确认里完成归档。P0-B 的效率闭环需要补齐“无合适节点时新增节点并归档”，让用户不必先跳出确认台手动建目录再回来。

## What Changes

- 路由 Agent 在判定 `no_suitable` 时，额外输出一条新节点建议：建议名称、可选父节点和理由；建议只作为候选，不得直接创建节点。
- `Candidate` 落库新节点建议字段（名称、父节点、理由），前端在无合适节点时展示并可编辑。
- 同一 Source 内多条候选建议相同路径时，前端聚合为一条节点建议展示；后端在创建节点时复用同名同父节点，避免重复建节点。
- 新增“新增节点并归档”原子接口：用户明确确认后，在同一个事务内完成节点创建（或复用）与候选归档，任一环节失败都不留半成品。
- `no_suitable` 分支的确认台交互：可继续选择最接近的已有节点，可暂存候选，也可新增节点并归档。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `routing-suggestions`: 路由阶段在 `no_suitable` 时输出并落库新节点建议；建议父节点必须是真实节点或根，且应用层校验后保存。
- `entry`: 新增“创建/复用节点并归档候选”的原子操作，复用现有 Entry 与证据写入逻辑。
- `candidate-review`: `no_suitable` 分支支持新节点建议展示、去重聚合与“新增节点并归档”确认动作。

## Impact

- 后端：`Candidate` 增加新节点建议字段并配套 Alembic 迁移；路由 Agent 输出与服务校验扩展；新增原子归档服务与 API；复用现有 Entry/证据逻辑；补充后端测试。
- 前端：`CandidatePayload` 增加新节点建议字段；`ReviewPage` 增加 `no_suitable` 分支的新节点交互与聚合提示；新增 API 客户端函数；补充前端测试。
- 无新外部依赖。

## Non-Goals

- 不做跨 Source 批量处理（`add-batch-candidate-review`）。
- 不做与已有 Entry 的关系判断、去重或补充来源（`add-entry-relation-suggestions`）。
- 不在本轮为 `recommended` / `needs_review` 状态提供“更改目录后新增节点”的完整入口；本轮只覆盖 `no_suitable` 分支。
- 不做 Directory Agent 目录共创或目录调整。
- 不展示模型自报的伪精确百分比。
