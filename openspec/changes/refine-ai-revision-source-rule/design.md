## Context

上一 change（`add-ai-revision-external-knowledge`）让应用 AI 修订时始终创建虚拟 Source。实测发现纯格式调整也会产生冗余来源：虚拟 Source 的定位是"非既有材料支撑内容"的可溯源载体，信息未变的整理不需要它。

## Goals / Non-Goals

**Goals:**

- 应用 AI 修订时，仅 `external_supplemented=true` 才创建虚拟 Source 与来源证据；
- 纯格式调整仍记版本，便于回退与审计；
- 前端应用时回传 `external_supplemented`。

**Non-Goals:**

- 不清理已有演示数据；不引入"实质修改"独立判断字段。

## Decisions

### D1：以 `external_supplemented` 作为是否建来源的判据

`apply_ai_revision_to_entry` 中，虚拟 Source 创建条件从 `changed` 改为 `changed and payload.external_supplemented`；版本快照与上下文刷新仍只依赖 `changed`。

理由：`external_supplemented` 是模型已在输出的字段（提示词约束"使用外部知识时必须为 true"），零新增模型输出；语义与"来源证据 = 非既有材料支撑内容"一致。AI 基于既有证据的内部重写（external=false）内容仍由原来源支撑，符合可溯源铁律。

### D2：应用请求回传标记

`ApplyRevisionSuggestionRequest` 增加可选 `external_supplemented`（默认 false）；前端在应用时取草稿的 `external_supplemented` 随字段一起提交。

### D3：版本行为不变

纯格式调整仍追加 `ai_revision` 版本与变更说明。版本历史的意义是"改了什么、能回退"，格式调整也应保留记录。

## Risks / Trade-offs

- [模型误标 external_supplemented] → 以模型标记为准（提示词已约束），UI 的「含 AI 外部补充」徽标可供用户复核。
- [内部实质重写不建来源] → 信息未变、原来源仍可溯源；如后续需要更细粒度，再做结构化 grounding（优化清单第 14 条）。

## Migration Plan

无数据库变更；已有冗余来源保留，不回填、不清理。

## Open Questions

- 无。
