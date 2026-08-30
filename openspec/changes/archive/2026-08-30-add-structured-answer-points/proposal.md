## Why

真机测试里，长回答（例如「哪些地方要提前预留插座」）在原生 App 中渲染成一整段平文本：回答模型其实已经输出了加粗、分组标题和列表，但客户端为了安全把所有 Markdown 标记剥掉，重点难找、信息层级缺失；同时引用只在底部横条平铺，无法逐条溯源。原型（`grove-mobile-agent-prototype.html`）的回答形态是「编号要点 + 行内引用」，需要把这条路径落地到正式回答。

## What Changes

- 后端回答协议新增可选 `points` 结构化字段：每条要点包含 `section`（可选分组标题）、`text`（正文）、`evidence_handles`（该条采用的证据句柄）；服务端按本 Run 账本重验句柄后，输出每条要点对应的 `citations`（复用 `KnowledgeRunCitationOut` 结构）。
- 回答模型输出升级为「`lead` 结论摘要 + `points` 要点列表」；服务端从 `lead` + `points` 确定性拼接 `answer` 纯文本，保持 Web ReaderView、草稿 seed 与历史消息内容不变，消除「模型同时写文本和结构」的双写漂移。
- 移动端 `AnswerCard` 在有 `points` 时渲染要点卡：分组标题、连续编号、要点正文、每条一个来源 chip（复用现有 CitationSheet）；无 `points` 的历史回答保留现有纯文本 + 底部引用条作为回退。
- 有 `points` 时底部引用条保留为「全部来源速览」，与原型一致。
- 无有效引用的要点由服务端丢弃并计入 `partial`；`points` 与既有 `citations` 语义一致，不改变调查、partial、insufficient、conflicts 的现有语义。

## Capabilities

### New Capabilities

- `structured-answer-points`: 回答结构化要点协议（`points` 字段、逐条句柄校验、服务端拼接 `answer` 文本）与原生要点卡渲染。

### Modified Capabilities

- `native-knowledge-agent-answer`: 回答正文展示要求从「平文本 + 底部引用条」扩展为「结构化要点卡 + 逐条引用，无 `points` 时回退平文本」，保持「基于正式知识」语义与 Candidate/正式 Entry 区分。

## Impact

- 后端：`KnowledgeAnswerDraft` / `KnowledgeAnswerOut` 增加 `points`；回答 prompt 升级；`build_validated_answer` 逐点校验句柄并拼接 `answer` 文本；相应单测。
- 移动端：`KnowledgeAnswer` 类型、`AnswerCard` 要点卡渲染与回退路径、组件测试。
- 不改 Web ReaderView、草稿/Candidate/正式 Entry 协议、调查与工作集逻辑。

## Non-Goals

- 不渲染 HTML、链接、图片、代码块等任意富文本；
- 不做前端解析正文猜测引用绑定（方案 B2），逐条引用必须来自服务端结构化数据；
- 不改变草稿/确认协议，不影响「整理成知识」链路；
- 不改变既有回答文本语义与 Web 端展示。
