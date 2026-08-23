## Context

修订建议此前被限制为「只基于现有来源证据」，无法满足用户「结合已有知识与外部知识」的求证/丰富诉求。产品讨论确认：AI 阅读保持只读知识库（项目意义所在）；知识补充/修订路径放开外部知识，AI 补充必须可辨识、可溯源。蓝图《目录与知识空间》的外部知识边界已更新。

## Goals / Non-Goals

**Goals:**

- Revision Agent 允许结合知识库与 AI 自身知识，回复文字标注来源、草稿标记 `external_supplemented`；
- 应用时创建「AI 修订建议」虚拟 Source（指令 + AI 输出 + provider/model）并加入来源证据；
- 前端草稿区显示「含 AI 外部补充」徽标，应用时回传 AI 元数据。

**Non-Goals:**

- 不改 AI 阅读；不做联网检索/Discovery；
- 不做结构化 grounding（逐条来源标注），记录为后续增强；
- 不持久化讨论过程，只在应用时沉淀虚拟 Source。

## Decisions

### D1：外部知识边界（读/补分离）

AI 阅读保持知识库内；修订建议路径允许结合外部知识。理由：读的价值在于可信地阅读自己的知识；改/补的价值在于让知识成长，AI 可以带来材料里没有的内容，但必须可辨识可溯源。

### D2：Agent 提示词与输出

提示词由「禁止外部知识」改为「优先使用知识库证据，不足时可用 AI 自身知识补充；回复中文字标注哪些是 AI 知识补充；草稿 `external_supplemented=true` 标记；不得编造来源证据（引用必须真实存在）」。`RevisionDraft` 增加 `external_supplemented: bool`，随 `RevisionSuggestionOut` 返回。

### D3：应用时沉淀虚拟 Source

`ApplyRevisionSuggestionRequest` 扩展可选字段：`instruction`、`ai_reply`、`reason`、`provider`、`model`（前端从最后一次生成/调整响应回传）。应用服务在实际修改时：

1. 创建虚拟 Source（标题「AI 修订建议：<Entry 标题>」，`note=指令`，归属当前 Project/Workspace）；
2. 创建 Attachment（kind=text，内容=AI 回复/草稿文本）；
3. 创建 Extraction（provider/model，满足 AI 可观测性）并标记为 active；
4. 创建 EntrySourceEvidence（指向虚拟 Source，`quote=变更说明`）；
5. 追加 `ai_revision` 版本与变更说明。

理由：沿用 AI 阅读问答的虚拟 Source 模式，保证「正式记录可溯源」铁律不破；只在应用（用户确认）时沉淀，对话过程仍不落库。

### D4：前端

- 对话状态记录最近一次响应的 `instruction / ai_reply / reason / provider / model`，应用时随请求回传；
- 草稿区在 `draft.external_supplemented=true` 时显示「含 AI 外部补充」徽标；
- 应用成功后失效查询并关闭面板（不变）。

## Risks / Trade-offs

- [AI 外部知识可能不准/过时] → 应用前 UI 标记 + 用户确认；虚拟 Source 记录原文可审计；P2 Review 后续做过期/冲突检查。
- [应用请求体积略增] → 回传的是短文本（指令/AI 回复），个人 KB 场景可接受。
- [来源列表变多] → 每条 AI 修订对应一条虚拟 Source，来源详情可展开查看，符合可溯源预期。

## Migration Plan

无数据库表变更；复用 Source/Attachment/Extraction 既有模型。回滚即撤销接口载荷与提示词改动。

## Open Questions

- 结构化 grounding（每条修改标注「来自材料 / AI 补充」）作为后续增强，待真实使用评估。
