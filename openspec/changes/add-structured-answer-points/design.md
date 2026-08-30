## Context

原生回答卡当前把 `answer` 正文当纯文本展示：客户端 `cleanAnswerText` 出于安全把所有 Markdown 标记（`**`、`##`、`-`）剥掉，长回答变成一整段平文本；引用只在底部横条平铺，无法逐条溯源。回答模型实际已经输出「结论 + 分组标题 + 列表」的结构，但没有可靠的结构化数据支撑逐条引用。原型 `grove-mobile-agent-prototype.html` 的回答形态是「编号要点 + 行内引用按钮」（`.answer-points`），本次把它落地为正式协议与原生渲染。

前置基线：`add-knowledge-agent-candidate-drafting` 已归档，回答协议为 `KnowledgeAnswerOut`（`answer` 文本 + 扁平 `citations` + `conflicts` + `coverage/gaps`），回答模型输出 `KnowledgeAnswerDraft`（`answer` 文本 + `citations` 句柄列表）。移动端 `AnswerCard` 用 `cleanAnswerText` 渲染正文并展示横向 `CitationStrip`。

## Goals / Non-Goals

**Goals:**

- 回答协议增加可选 `points` 结构化字段：每条含 `section`（可选分组）、`text`、该条采用的证据句柄；服务端按本 Run 账本逐条重验。
- 回答模型输出升级为「`lead` 结论摘要 + `points` 要点列表」；`answer` 文本由服务端从 `lead` + `points` 确定性拼接，保持 Web ReaderView、草稿 seed 与历史消息内容兼容。
- 原生回答卡在有 `points` 时渲染要点卡：分组标题、连续编号、要点正文、每条一个来源 chip；无 `points` 的历史回答回退到现有平文本 + 引用条。
- 逐条引用只来自服务端结构化数据，不做前端猜测式绑定。

**Non-Goals:**

- 不渲染 HTML、链接、图片、代码块等任意富文本；
- 不做前端解析正文猜测引用绑定（方案 B2）；
- 不改变草稿/确认协议、「整理成知识」链路与正式 Entry 语义；
- 不改变调查、partial、insufficient、conflicts 的既有语义；
- 不修改 Web ReaderView 的展示方式。

## Decisions

### 1. `points` 为可选字段，旧回答零迁移

`KnowledgeAnswerOut` 增加 `points: list[KnowledgeAnswerPointOut] = []`，`KnowledgeAnswerDraft` 增加 `lead: str | None` 与 `points`。历史 `answer_json` 没有 `points`，Pydantic 默认空列表即可解析，无 DB 迁移。

移动端 `KnowledgeAnswer` 增加 `points?: KnowledgeAnswerPoint[]`；`AnswerCard` 仅在 `points` 非空时切换要点卡渲染，否则走现有 `cleanAnswerText` + `CitationStrip` 回退路径，保证旧回答与旧缓存不回归。

### 2. 单一事实源：模型输出 `lead + points`，服务端拼接 `answer`

不再让模型同时写「文本」和「结构」两份内容（会漂移、多耗 token）。模型只输出结构化 `lead` + `points`；`answer` 由服务端确定性拼接：

```
lead（若有，单独一段）

**section 1**
- point text
- point text

**section 2**
- point text
```

拼接格式刻意模仿现有模型输出（`**分组**` + `- 列表`），Web ReaderView 与草稿 seed 看到的文本风格不变。`sanitize_answer_text` 继续用于 `lead`/`text`，防句柄泄漏。

**兼容路径**：若模型未输出 `points`（旧模型/降级/解析失败），`build_validated_answer` 走现有逻辑——`answer` 取 `draft.answer` 清洗后原样返回，扁平 `citations` 照旧。

### 3. 逐条句柄校验与派生 `citations`

当 `points` 存在时：

- 每条 `evidence_handles` 去重、只保留本 Run 可引用句柄（`evidence_rows_for_handles` + `is_citable`）；
- 无有效句柄的 point 整条丢弃，并计入 `discarded_count`（触发 `partial`）；
- 最终扁平 `citations` 由服务端按 points 顺序去重派生，再并入 conflicts 双方句柄——模型不再需要同时输出扁平 citations，避免两处不一致；
- `coverage`/`gaps`/`conflicts`/`status` 判定沿用现有 `build_validated_answer` 规则，不做新语义。

### 4. Prompt v3 与降级策略

`KNOWLEDGE_ANSWER_SYSTEM_PROMPT` 升到 v3：要求 `lead` 首句直接回答、每个独立关键事实一个 point、每个 point 至少一个句柄、`section` 用于空间/主题分组、`text` 内禁止句柄/编号/括号标记。`ANSWER_PROMPT_VERSION` 记录为 `v3`，模型调用可观测性字段不变。

模型不可用/结构化输出失败时沿用现有确定性 `insufficient` 降级，不伪造成功。

### 5. 原生要点卡渲染与触控（最终版：分组 + 连续编号 + 底部全部来源速览）

真机反馈两轮：第一版「每条要点下方一个来源 chip」在「一条要点 = 一条 Entry」时来源标题
与要点内容高度重复、显得多余；第二版「行内上标 + 底部按序号来源区」把来源全部铺开又太长，
且用户希望保留每条要点左侧的连续编号。最终方案：

- 分组标题：`section` 变化时渲染一行加粗标题（带 `▍` 前缀符号）；
- 每条要点：左侧绿色圆底**连续编号 `1..N`**（对齐原型 `point-number`）+ 正文；
- 不在要点内展示任何来源（无逐条 chip、无行内上标）；逐条绑定只保留在数据层（整理成
  知识、冲突等仍按引用工作）；
- 底部统一保留 `CitationStrip`「全部来源速览」（有 `points` 与无 `points` 一致），
  点击 chip 复用现有 `onCitationPress` → `CitationSheet`；
- 读屏：编号与分组标题保持可读文本；底部来源 chip `accessibilityLabel="查看引用：
  {entryTitle}"`；
- 无 `points` 的历史回答仍回退到现有纯文本 + 底部 `CitationStrip`，不回归。

## Risks / Trade-offs

- [模型输出 points 不稳定（section 乱序、句柄重复、text 混入句柄）] → 服务端白名单过滤、无效 point 丢弃并计入 `partial`，`text` 再经 `sanitize_answer_text` 清洗；不会把无依据要点写入展示。
- [拼接文本与模型手写文本风格存在细微差异] → 拼接格式刻意复刻现有「**分组** + `- 列表」形态，Web 端与历史体验基本一致。
- [token 成本略增（points 内句柄重复出现）] → 接受，量级约 10-20%，回答延迟影响很小；在 validation 中记录。
- [旧回答无 points 造成新旧视觉不一致] → 回退路径保证功能不回归；后续如需统一可另立 change 做历史数据回填，不在本次范围。

## Migration Plan

1. 后端：扩展两个 Pydantic 模型与 `build_validated_answer`（纯 JSON 结构变化，无 DB 迁移、无 Alembic 变更）；
2. 升级回答 prompt 至 v3，`ANSWER_PROMPT_VERSION` 同步；
3. 移动端：扩展类型 + `AnswerCard` 要点卡渲染与回退，补组件测试；
4. 回滚：服务端 `points` 字段为可选，旧客户端忽略新字段不受影响；移动端旧回答走回退路径，任一端先回滚均不破坏另一端。

## Open Questions

- 无（`section` 样式、编号连续、保留底部引用条、来源 chip 放要点下方等取舍已在本文档确定，实施时按此执行）。
