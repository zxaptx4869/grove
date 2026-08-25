## Context

确认台证据高亮用 `原文.indexOf(引用)` 精确匹配，而 AI 生成的引用把原文换行压成空格、标点可能全角/半角混用，导致大多数引用匹配失败。来源审阅弹窗（`SourceCandidatesDialog`）只展示引用文本，没有原文。

## Goals / Non-Goals

**Goals:**

- 高亮稳定命中：忽略空白、标点、大小写差异；
- 切换候选自动定位到高亮；
- 来源审阅弹窗展示原文并支持高亮与定位。

**Non-Goals:**

- 不改证据引用生成（organizing agent）；
- 不做图片像素级证据定位；
- 不改确认流程与候选操作。

## Decisions

### D1：归一化匹配工具

新增 `frontend/src/lib/evidenceHighlight.ts`：

- `normalizeText(text)`：去全部空白（含换行）、全角标点转半角、英文转小写；
- `findEvidenceRange(text, quote)`：归一化后定位引用，通过「归一化字符 → 原文索引」映射返回原文区间 `{ start, end } | null`；
- `highlightEvidence(text, quote)`：返回高亮片段（命中区间包 `<mark>`）。

### D2：确认台定位

`ReviewPage` 监听 `currentCandidate.id` 变化（`useEffect`），在渲染后查找证据区内第一个高亮 `<mark>`，`scrollIntoView({ behavior: 'smooth', block: 'center' })`；无匹配时不滚动。

### D3：来源审阅弹窗

`SourceCandidatesDialog` 增加来源原文区（复用 `fetchSource` 取附件 OCR/正文，渲染结构与确认台一致）；新增「选中候选」状态（默认第一条），点击候选卡片选中，原文高亮对应证据并自动定位；弹窗由纯列表变为「原文 + 候选列表」双栏（弹窗内布局）。

## Risks / Trade-offs

- [归一化导致多匹配] → 取第一个命中，保持与现状一致；极端模糊引用宁可不高亮也不误标。
- [弹窗布局变化] → 弹窗宽度提升为双栏，内容变多但可滚动；与确认台交互统一。

## Migration Plan

无后端与数据变更。

## Open Questions

- 无。
