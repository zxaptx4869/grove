## Context

实测组织 Agent 对未归属来源偶尔漏输出 `recommended_project_id`（长输入时更明显），即使内容明显属于某项目。根因是提示词允许「不确定时留空」且该字段可选。方案：提示词改为必答，模型仍漏时应用层重试一次。

## Goals / Non-Goals

**Goals:**

- 未归属来源项目推荐成为必答项；
- 模型漏输出时重试一次并采纳有效推荐；
- 重试不改变首次提取的候选。

**Non-Goals:**

- 不改候选拆分质量；
- 不改已归属来源行为。

## Decisions

### D1：提示词必答

组织 Agent 规则 7 改为：未归属来源 MUST 从「可选项目」选择最合适项目并输出 `recommended_project_id`（数字 id）与 `project_recommendation_reason`；只有确实没有合适项目时才可为空并说明原因。

### D2：应用层重试

`run_organizing_agent` 中，若 `project is None and workspace_projects and draft.recommended_project_id is None`，用追加的强调上下文重跑一次（不换模型、retries 保持 1）；重试输出若包含属于可选项目的 `recommended_project_id`，则只把该推荐与理由写回首次草稿，候选与标题保持首次结果；无效 id 或仍为空则保持原样。

## Risks / Trade-offs

- [重试增加一次模型调用] → 仅发生在「未归属 + 可选项目 + 首轮漏推荐」时，频率低；用有效 id 校验避免采纳幻觉 id。
- [重试仍失败] → 保持未归属，与现状一致，不阻塞处理。

## Migration Plan

无数据库变更。

## Open Questions

- 无。
