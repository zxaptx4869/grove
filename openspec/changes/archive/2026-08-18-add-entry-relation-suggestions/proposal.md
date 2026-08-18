## Why

确认台目前只围绕候选自身的内容、类型和目录做决定，看不到项目里已经存在的正式 Entry。批量快审会直接把「疑似重复 / 可以补充 / 可能冲突」的候选当作新知识归档，容易制造重复知识或把冲突内容仓促落成正式 Entry。本 change 在归档前增加一次「与已有 Entry 的关系判断」，把新建、疑似重复、可以补充、可能冲突四类建议落到候选上，并为补充来源和修订草稿提供确认动作。

## What Changes

- 在 Organizing 处理任务内新增关系判断步骤，顺序为「提取 → 路由 → 关系判断」。
- 新增项目内相似 Entry 检索：基于标题归一化相等、标题包含和字符 bigram 重叠做轻量召回，不引入向量或 embedding。
- 为每条候选落库关系建议：`new` / `duplicate` / `supplement` / `conflict`，以及目标 Entry、判断理由和修订草稿。
- `duplicate` 时只为已有 Entry 补充新 Source 证据，不创建新 Entry。
- `supplement` 时生成 Entry 修订草稿，用户确认后应用到已有 Entry。
- `conflict` 时进入精审，由用户并列保留、修订或忽略。
- 批量快审/精审分流规则纳入关系建议，`duplicate / supplement / conflict` 自动进入精审。
- 确认台与批量视图展示关系建议及对应操作，仍保留「按新知识创建」的兜底入口。

## Non-Goals

- 不实现语义/向量检索、embedding、FTS 或新依赖；语义检索留给 P1 `add-semantic-retrieval`。
- 不做跨项目相似检索或全局关系判断，只做项目内检索。
- 不自动执行关系建议：补充来源、应用修订必须用户确认。
- 不引入独立 `EntryRevision` 或完整版本历史；修订草稿只是候选上的临时建议。
- 不实现 `enhance-project-context-with-entries`，本 change 不依赖也不增强项目上下文快照。
- 不做 P2 的定期 Review、Knowledge Gap、跨项目引用，也不做类型/来源/风险筛选和整批原子回滚。
- 不改变现有 `/api/search` 用户搜索语义。

## Capabilities

### New Capabilities

- `entry-relation-suggestions`: 项目内相似 Entry 检索、四种关系建议、补充来源证据与 Entry 修订草稿的生成、确认和应用。

### Modified Capabilities

- `candidate-review`: 按 Source 审阅时支持关系建议展示，并允许候选关联到已有 Entry（补充来源 / 应用修订 / 并列保留 / 忽略）。
- `batch-candidate-review`: 快审与精审分流规则纳入关系建议，`duplicate / supplement / conflict` 不再进入批量快审。

## Impact

- 后端：`Candidate` 模型新增关系建议字段；新增关系判断 Agent 与服务、相似 Entry 检索服务、两个确认接口；Alembic 迁移。
- 前端：`ReviewPage` 与 `BatchReviewView` 增加关系建议展示和对应操作；`CandidatePayload` 类型扩展。
- 数据：新增 `Candidate` 可空字段，无回填，不新增独立关系对象。
- 依赖：无新增第三方依赖。
