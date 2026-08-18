## Context

确认台已经能把候选归档为 Entry，批量视图也已把推荐明确且无风险的候选自动分流到快审。但当前候选没有任何“与已有 Entry 关系”的信息，批量快审会把疑似重复、可以补充或可能冲突的候选直接当作新知识归档，容易产生重复知识和仓促冲突。

前序 change 已确立的落库风格：AI 建议挂在 `Candidate` 上，用可空列或 JSON 文本存储，无外键，应用层校验；路由步骤独立于提取步骤，在 `OrganizingProcessingProvider` 内串行调用。本 change 延续这一风格，新增关系判断步骤。

## Goals / Non-Goals

**Goals:**

- 在 Organizing 处理任务内新增关系判断步骤，顺序为「提取 → 路由 → 关系判断」。
- 项目内确定性相似 Entry 检索，不引入向量或 embedding。
- 为每条候选落库四种关系建议：`new` / `duplicate` / `supplement` / `conflict`。
- 疑似重复时只为已有 Entry 补充来源证据；可以补充时生成并应用修订草稿；冲突进入精审。
- 批量快审分流规则纳入关系建议。

**Non-Goals:**

- 语义/向量检索、FTS、新依赖；
- 跨项目相似检索；
- 自动执行关系建议（补来源/应用修订必须用户确认）；
- 独立 `EntryRevision` 或完整版本历史；
- `enhance-project-context-with-entries`；
- P2 定期 Review、Knowledge Gap、跨项目引用、筛选器和整批回滚。

## Decisions

### D1：关系判断是独立步骤，不修改提取 Agent

新增 `agents/relation.py`（`run_relation_agent`）与 `services/entry_relation.py`（检索与编排），在 `OrganizingProcessingProvider` 内于 `route_source` 之后调用。关系判断依赖项目内已有 Entry，且需要独立重跑，因此不能塞进提取 prompt。

理由：与现有“提取/路由两个独立步骤”一致；职责单一，便于单独测试和未来被其他能力复用。

### D2：相似检索用确定性关键词/字符召回

新增内部检索服务，加载项目内已确认 Entry 后，在 Python 内对每条候选做轻量打分：

- 标题归一化相等；
- 标题互相包含；
- 标题/内容的字符 bigram 重叠（忽略空白与标点）。

按分排序取 top-K（默认 5）交给关系 Agent。项目内无 Entry 时直接标记所有候选为 `new`，不调用 AI。

理由：P0 数据量为个人知识库，确定性召回可解释、可测试、无新依赖；语义检索留给 P1 `add-semantic-retrieval`。

### D3：关系建议落在 Candidate

`Candidate` 新增可空字段：

- `relation_status`：`String(16)`，默认 `pending`，取值 `pending` / `new` / `duplicate` / `supplement` / `conflict`；
- `relation_target_entry_id`：`BigInteger`，可空，无外键，应用层校验；
- `relation_reason`：`Text`，可空；
- `revision_draft`：`Text`，可空，JSON 文本。

理由：关系建议是候选级临时建议，与 `recommended_node_id`、`new_node_*` 的取舍一致，避免本轮引入独立关系实体。

### D4：关系状态与降级规则

关系 Agent 输出结构化 `RelationDraft`，应用层校验后落库：

- `conflict`：存在矛盾或重复/补充判断不清但风险明显；
- `supplement`：相关且有新增/更新内容，必须有目标 Entry 和修订草稿；
- `duplicate`：同一知识且无新增实质内容，必须有目标 Entry；
- `new`：无相关 Entry 或关系不成立。

降级顺序：`conflict` 优先；`duplicate` / `supplement` / `conflict` 目标非法时降级为 `new`；`supplement` 缺修订草稿时降级为 `duplicate`。

理由：模型输出始终是候选，应用层用确定性规则兜底，避免非法 target 或缺失草稿进入正式操作。

### D5：两个新的候选确认动作

新增：

```text
POST /api/candidates/{candidate_id}/add-evidence
POST /api/candidates/{candidate_id}/apply-revision
```

- `add-evidence`：校验候选 `pending` 且目标 Entry 属于候选所属项目；把候选 `evidence_refs` 追加为目标 Entry 的证据；候选 `status=confirmed`、`entry_id=target`。不修改 Entry 内容。
- `apply-revision`：校验同项目；按“缺省不改、可空字段传 null 表示清空”更新目标 Entry；追加来源证据；候选 `status=confirmed`、`entry_id=target`。

两者在同一事务内完成，任何失败在提交前抛出并回滚。提取现有 `archive_candidate` 中“候选证据转 Entry 证据”的逻辑为共享 helper，避免重复。

理由：显式表达“补来源”和“应用修订”两个组合动作，避免扩展现有 `/archive` 接口造成联合校验复杂度；与 `archive-with-new-node` 的拆分思路一致。

### D6：触发时机与失败回退

`OrganizingProcessingProvider.process()` 在路由成功后同步执行关系判断：

- 项目内无已确认 Entry：所有候选 `relation_status=new`，不调用 AI；
- 项目内有 Entry：检索 top-K 相似 Entry 后调用关系 Agent；
- 关系判断失败：记录日志，候选保持 `pending`（视为未判断，按新知识处理），不阻塞处理任务完成。

用户修改 Source 项目时，复用/新增 `clear_candidate_relations`，与 `clear_candidate_routing` 一起清除旧关系建议，再在 `route_source` 后重跑关系判断。

理由：关系建议是增强，不是核心闭环的硬依赖；失败应静默降级，让确认台仍可正常工作。

### D7：批量快审分流纳入关系建议

扩展 `_review_band`：

```text
quick 当且仅当：
  candidate_kind == recommended
  AND routing_status == recommended
  AND recommended_node_id 非空
  AND risk_flags 为空
  AND relation_status ∈ {pending, new}
```

`duplicate` / `supplement` / `conflict` 一律 `detailed`，因为它们的动作不是“新建 Entry”，需要人在环上确认。

### D8：前端展示与兜底动作

`CandidateOut` / `ReviewCandidateOut` 增加关系字段，并附带目标 Entry 的 `title` 与 `node_name`（列表服务批量查询，避免 N+1）。

`ReviewPage` 的候选编辑器按关系状态分叉：

- `new` / `pending`：保持现有采纳/拒绝/跳过/新增节点归档；
- `duplicate`：主按钮「补充来源证据」，副按钮「仍按新知识创建」；
- `supplement`：展示可编辑修订草稿，主按钮「应用修订」，副按钮「仍按新知识创建」；
- `conflict`：提供「并列保留」「修订现有」「忽略」。

`BatchReviewView` 的 `routingReason` 优先展示关系信号（疑似重复 / 可补充 / 可能冲突 + 理由）。

### D9：修订草稿 JSON 结构

`revision_draft` 存建议的最终字段全集与修改说明：

```text
{
  "title": "...", "content": "...", "main_type": "...",
  "info_nature": null, "applicable_condition": null, "note": null,
  "change_summary": "..."
}
```

前端展示目标 Entry 当前字段与草稿字段，允许编辑后再应用。

## Risks / Trade-offs

- [关系 Agent 输出非法 target 或缺失草稿] → 应用层按 D4 降级，非法值不进入正式操作。
- [字符 bigram 召回对中文同义表达不敏感] → 本 change 只承诺“基本相似检索”，语义检索留给 P1；召回不足时关系 Agent 仍可判定为 `new`，不阻断归档。
- [关系判断是额外 AI 调用，增加处理耗时] → 与路由一样在 Worker 内串行，失败静默回退；项目内无 Entry 时零额外调用。
- [补来源/应用修订写入正式 Entry] → 仅在用户确认后执行，且同一事务内完成，保持可溯源。
- [前端缓存旧关系建议] → mutation 显式失效 `sourceCandidates`、`reviewCandidates`、`reviewSources`、`projectTree`。
- [全项目内存检索随 Entry 增长变慢] → P0 个人知识库规模可接受；未来语义检索替换检索层，服务边界已隔离。

## Migration Plan

一个 Alembic 迁移为 `candidates` 增加四个可空列，无回填；老候选 `relation_status` 保持 `pending`，确认台按未判断处理。回滚即删列。无破坏性变更。

## Open Questions

- 相似检索的 bigram 阈值与 top-K 数值在实施时用真实数据集校准，不阻塞本 change。
- 修订草稿前端是否做逐字段 diff 或仅展示 `change_summary` + 可编辑最终值，实施时按 Grove UI 规范确定。
