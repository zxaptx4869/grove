## Why

AI 修订建议目前被限制为「只基于现有来源证据」，无法满足用户「结合已有知识与外部知识」的诉求（求证、丰富）。同时要保持 AI 阅读的定位（只读知识库，否则项目失去意义）。因此需要在知识补充/修订路径放开外部知识，并保证 AI 补充内容可辨识、可溯源。

## What Changes

- Revision Agent 允许结合知识库证据与 AI 自身知识：回复中以文字标注区分「材料/知识库内容」与「AI 知识补充」，草稿增加 `external_supplemented` 标记；不得编造来源证据。
- 应用 AI 修订草稿时创建「AI 修订建议」虚拟 Source（记录用户指令、AI 回复/草稿与 provider/model），加入 Entry 来源证据，并追加 `ai_revision` 版本；UI 在草稿区显示「含 AI 外部补充」徽标。
- 蓝图外部知识边界更新：AI 阅读保持知识库内；知识补充/修订路径先行试点外部知识；联网发现仍后置。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `entry`: 「AI 修订建议生成与对话调整」允许结合外部知识且输出可辨识；「应用 AI 修订建议」应用时沉淀虚拟 Source 并加入来源证据。

## Impact

- 后端：`agents/revision.py`（提示词与 `external_supplemented` 输出）、`schemas/entry.py`（应用请求携带指令/AI 输出/provider/model；草稿负载增加标记）、`services/entry.py`（应用时创建虚拟 Source + Attachment + Extraction + 证据）。
- 前端：`lib/api.ts` 类型；`RevisionSuggestionDialog.tsx` 回传 AI 元数据并显示「含 AI 外部补充」徽标。
- 测试：后端应用沉淀虚拟来源、外部补充标记；前端徽标与元数据回传。
- 文档：蓝图外部知识边界更新。
- 数据与依赖：无数据表变更（复用 Source/Attachment/Extraction），无新增依赖。

## Non-Goals

- 不改 AI 阅读：保持只读知识库，不用模型自身知识悄悄补齐。
- 不做结构化 grounding（每条修改标注「来自材料 / AI 补充」）——记录为后续增强。
- 不做联网检索与 Discovery（仍后置）。
- 不持久化讨论过程本身；只在应用时沉淀虚拟 Source。
