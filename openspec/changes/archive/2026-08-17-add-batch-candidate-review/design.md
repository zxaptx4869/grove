## Context

确认台当前只有按 Source 逐条审阅；`batch-decision` 接口只改状态、不创建 Entry，且未接入前端。本 change 增加批量处理模式：跨 Source 平铺候选、按推荐目录分组、批量确认/拒绝/改目录，并把高风险候选自动分流到精审。

## Goals / Non-Goals

**Goals:**

- 确认台内提供「按采集审阅 / 批量处理」切换，两个视图共享候选池。
- 快审只处理「推荐明确 + 无风险」的推荐候选；其余进精审。
- 批量确认逐条创建 Entry，partial 成功/失败，失败项可重试。
- 支持统一目录节点覆盖候选自身推荐。

**Non-Goals:**

- 不做与已有 Entry 的关系建议（冲突/疑似重复标签留给 `add-entry-relation-suggestions`）。
- 不做类型/来源/风险筛选器。
- 不做跨项目批量。
- 不做整批原子回滚。

## Decisions

### D1：两个新接口

```text
GET  /api/projects/{project_id}/review/candidates
       → 项目内全部待采纳候选（含 source_title/source_note/review_band）

POST /api/projects/{project_id}/review/candidates/batch-decision
       body: { candidate_ids, action: confirm|reject, node_id? }
       → 逐条结果 [{candidate_id, status: confirmed|rejected|failed, error?}]
```

理由：列表接口给前端一次拿到分组与分流所需全部字段；批量接口按候选逐条处理，天然支持 partial。

### D2：快审/精审分流规则

`review_band = quick` 当且仅当：

- `candidate_kind == recommended`；
- `routing_status == recommended`；
- `recommended_node_id` 非空；
- `risk_flags` 为空。

其余（`needs_review`、`no_suitable`、`other`、有任何风险标记）一律为 `detailed`。规则由后端计算，前端只消费。

理由：本轮没有关系建议数据，只能基于现有路由状态与风险标记做确定性分流；冲突/重复等关系标签是下一 change 的增量。

### D3：批量确认 partial 语义

`confirm` 逐条调用现有 `archive_candidate`：成功即 `commit` 并记录成功；失败先 `rollback` 再记录失败原因，继续处理下一条。`reject` 直接改状态并提交。

理由：蓝图明确“两个视图共享候选池、不存在整 Source 自动全采纳”，partial 比整批回滚更符合真实整理节奏，失败项留在列表可重试。

### D4：统一目录覆盖

`confirm` 时若请求带 `node_id`，则所有选中候选归档到该节点；否则使用候选自身 `recommended_node_id`。无节点可用的候选在批量确认中返回失败原因，引导精审。

### D5：前端分组与交互

- `ReviewPage` 增加 `mode` 状态与 segmented 切换；批量视图独立为 `BatchReviewView` 组件。
- 批量视图用树接口把 `recommended_node_id` 解析为路径，按路径分组显示数量。
- 工具栏：已选计数、批量确认并归档、批量拒绝、修改目录（节点选择弹层，只存前端 `overrideNodeId`，不落库）。
- `detailed` 候选集中展示在「已分流精审」区，勾选禁用，「精审」按钮切回按采集审阅并定位到对应 Source。
- 变更通过 `useGroveMutation`，失效 `review-candidates`、`review-sources`、`project-tree`；确认后节点计数同步刷新。

## Risks / Trade-offs

- [批量确认部分失败时数据不一致观感] → 响应明确逐条结果，前端 toast 汇总“成功 N / 失败 M”，失败项保持待采纳可重试。
- [统一目录节点被删除或换项目] → 后端归档时沿用现有节点归属校验，非法节点整条失败并提示。
- [精审定位到候选需要跨请求] → 切换到 Source 模式后按 `focusCandidateId` 在候选加载完成后定位，定位失败则停留在该 Source 首条。

## Migration Plan

纯新增接口与前端视图，无数据迁移；回滚即移除接口与批量组件。

## Open Questions

无。
