## MODIFIED Requirements

### Requirement: 回答输出可选的结构化要点
回答协议 MUST 在 `KnowledgeAnswerOut` 中提供可选 `points` 结构化字段，每个要点 MUST 包含 `section`（可选分组标题）、`text`（要点正文）与逐条 `citations`（该要点采用的证据）；复合回答要点还 MUST 可选携带服务端校验后的 `requirement_ids`，内部模型草稿可以引用当前计划允许的 Evidence/result handles。Evidence 句柄 MUST 只来自本 Run 服务端核验过的可引用 Evidence；结构化 result handle MUST 只来自本 Run 已完成工具结果；客户端 MUST NOT 直接提交要点内容、回答义务或引用。

#### Scenario: 有结构要点的正常回答
- **WHEN** 回答模型返回 `lead` 结论摘要与多条 `points`，且每条 Evidence 句柄均可核验
- **THEN** 服务端返回 `points`（含分组、正文、逐条 `citations` 和可选 requirement ids），并按 `lead` + `points` 确定性拼接 `answer` 纯文本

#### Scenario: 复合要点覆盖多个义务
- **WHEN** 一个合法解释要点同时回答比较义务和建议义务
- **THEN** 服务端可以保留两个已存在的 requirement id，并分别把该要点计入对应义务覆盖

#### Scenario: 服务端工具事实要点
- **WHEN** 复合回答包含结构化 count 或 group_count 输出
- **THEN** 服务端根据实际工具结果生成不可由模型改写数值和完整性措辞的 point，并绑定对应 requirement ids；它不生成 Grove Citation

#### Scenario: 部分要点句柄失效
- **WHEN** `points` 中某条的 Evidence/result 句柄在本 Run 中不可引用、失效或与 requirement 无关联
- **THEN** 服务端丢弃非法绑定或该条并计入失效计数，保留其余有效要点，按逐项覆盖将回答状态标记为 partial 或 insufficient

#### Scenario: 全部 Grove-only 要点句柄失效
- **WHEN** `grove_only` 义务的所有 point 句柄均无法核验且没有合法工具事实
- **THEN** 服务端把该义务标记 insufficient，不保留无来源要点；若其他义务仍有合法内容则整体为 partial

#### Scenario: 历史或旧模型回答没有要点绑定
- **WHEN** 历史 `answer_json` 或旧模型输出不包含 `points` 或 requirement ids
- **THEN** 服务端沿用现有 `answer` 文本与扁平 `citations` 行为，协议保持兼容且不反向猜测回答义务

### Requirement: 要点文本与服务端拼接
服务端 MUST 在 `points` 存在时以结构化数据为单一事实源生成 `answer` 文本：`lead` 作为结论摘要，分组变化时输出分组标题，每条要点输出为列表项；复合回答 MUST 按规范化回答义务的自然顺序组织对应模型要点和服务端工具事实。`lead` 与要点正文 MUST NOT 包含 `ev_`、内部 result handle 或引用标识，模型 MUST NOT 在普通文字中替代、改写服务端工具事实的数值与完整性边界。

#### Scenario: 拼接格式稳定
- **WHEN** 服务端从 `lead` + 普通 points + tool fact points 生成复合 `answer`
- **THEN** 输出按回答义务自然顺序组织为「结论摘要 + 分组标题 + 列表项」，Web、原生端与历史展示语义保持一致

#### Scenario: 文本泄漏句柄
- **WHEN** 模型在 `lead` 或要点正文中写入 Evidence/result 句柄
- **THEN** 服务端清洗后输出，结构化 `citations` 和内部工具事实关联仍是唯一依据来源

#### Scenario: 模型试图改写精确工具事实
- **WHEN** 模型解释性 point 给出与 complete count 工具事实不同的数值，或把 limited 统计描述为全部
- **THEN** 服务端不采用冲突的模型数值表达，保留确定性 tool fact 并把相关解释标记无效或 partial

#### Scenario: 缺少一个回答义务
- **WHEN** 首次模型输出没有任何 point 绑定某个可回答 requirement id
- **THEN** 输出校验最多重试一次且不调用新工具；重试后仍缺少时，服务端在 gaps 中保留该义务并按 partial/insufficient 拼接已有合法内容
