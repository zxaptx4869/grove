## ADDED Requirements

### Requirement: 回答正文的要点卡渲染
原生 App MUST 在 `answer.points` 非空时把回答正文渲染为要点卡：分组标题、全回答连续编号、要点正文与逐条来源入口；MUST 在 `points` 缺失或为空时回退为现有纯文本正文 + 底部来源条，历史回答不得出现回归或伪富文本。

#### Scenario: 新回答带结构化要点
- **WHEN** 回答包含 `points` 且至少一条有效要点
- **THEN** 页面按分组标题、连续编号展示每条要点，并在每条下方提供该条的来源入口

#### Scenario: 历史回答无要点
- **WHEN** 回答不包含 `points`（历史数据或旧模型输出）
- **THEN** 页面保留现有纯文本正文与底部来源条，不显示空要点区

#### Scenario: 分组标题与编号可读
- **WHEN** 要点存在 `section` 分组
- **THEN** 分组标题以更醒目的样式展示，编号跨全回答连续且读屏可朗读

### Requirement: 逐条来源入口可核验可访问
原生 App MUST 为每条要点提供可点击的来源入口，点击后展示对应 Source 原文与 Entry 摘要；入口 MUST 达到 44×44 触控目标并提供读屏标签，且 MUST NOT 把 AI 即时回答、草稿或 Candidate 标为正式知识。

#### Scenario: 点击要点来源
- **WHEN** 用户点击某条要点的来源入口
- **THEN** 打开证据原文 Sheet，展示该条引用的 Entry 与 Source 原文，来源关系由应用层校验

#### Scenario: 触控与读屏
- **WHEN** 用户使用读屏或小尺寸触控
- **THEN** 来源入口提供 `查看引用：{Entry 标题}` 语义且最小触控高度为 44

#### Scenario: 语义不混淆
- **WHEN** 回答、草稿与待确认 Candidate 同屏出现
- **THEN** 要点卡保持「基于正式知识」的即时回答语义，不出现「已归档」或「正式知识」文案
