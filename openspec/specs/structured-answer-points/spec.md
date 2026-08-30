# structured-answer-points Specification

## Purpose
TBD - created by archiving change add-structured-answer-points. Update Purpose after archive.
## Requirements
### Requirement: 回答输出可选的结构化要点
回答协议 MUST 在 `KnowledgeAnswerOut` 中提供可选 `points` 结构化字段，每个要点 MUST 包含 `section`（可选分组标题）、`text`（要点正文）与逐条 `citations`（该要点采用的证据）；`points` 的每条句柄 MUST 只来自本 Run 服务端核验过的可引用 Evidence，客户端 MUST NOT 直接提交要点内容或引用。

#### Scenario: 有结构要点的正常回答
- **WHEN** 回答模型返回 `lead` 结论摘要与多条 `points`，且每条句柄均可核验
- **THEN** 服务端返回 `points`（含分组、正文与逐条 `citations`），并按 `lead` + `points` 确定性拼接 `answer` 纯文本

#### Scenario: 部分要点句柄失效
- **WHEN** `points` 中某条的句柄在本 Run 账本中不可引用或失效
- **THEN** 服务端丢弃该条并计入失效计数，保留其余有效要点，回答状态标记为 `partial`

#### Scenario: 全部要点句柄失效
- **WHEN** `points` 的所有句柄均无法核验
- **THEN** 服务端按无有效引用规则返回 `insufficient`，不保留无来源要点

#### Scenario: 历史或旧模型回答没有要点
- **WHEN** 历史 `answer_json` 或旧模型输出不包含 `points`
- **THEN** 服务端沿用现有 `answer` 文本与扁平 `citations` 行为，协议保持兼容

### Requirement: 要点文本与服务端拼接
服务端 MUST 在 `points` 存在时以结构化数据为单一事实源生成 `answer` 文本：`lead` 作为结论摘要，分组变化时输出分组标题，每条要点输出为列表项；`lead` 与要点正文 MUST NOT 包含 `ev_` 开头的句柄或引用标识。

#### Scenario: 拼接格式稳定
- **WHEN** 服务端从 `lead` + `points` 生成 `answer`
- **THEN** 输出按「结论摘要 + 分组标题 + 列表项」的稳定格式组织，Web 与历史展示语义保持一致

#### Scenario: 文本泄漏句柄
- **WHEN** 模型在 `lead` 或要点正文中写入 `ev_` 句柄
- **THEN** 服务端清洗后输出，结构化 `citations` 仍是唯一引用来源

