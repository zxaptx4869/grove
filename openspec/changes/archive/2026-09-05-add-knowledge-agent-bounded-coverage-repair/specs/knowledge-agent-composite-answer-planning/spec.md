## ADDED Requirements

### Requirement: 首次 coverage 可以触发一次受控缺口补查
系统 MUST 保持首次 `CompositeAnswerPlan` 不变，并在首次合法综合与逐项 coverage 持久化后，最多针对可修复的 `partial/insufficient` 义务进行一次有界补查。最终综合 MUST 只使用首次和补查阶段已提交的合法 Evidence、tool fact、允许的用户陈述与依据边界，并重算逐项 coverage、answer basis、Citation、gaps 和 Run 终态；补查失败 MUST 保留首次合法回答。

#### Scenario: 补查改善一项义务
- **WHEN** 首次 coverage 的某项 Grove 义务为 `insufficient`，补查产生了与该义务合法关联的新 Evidence
- **THEN** 最终综合可将该义务改为 `answered/partial`，其他已回答义务沿用原合法依据且首次计划摘要不变

#### Scenario: 补查后仍有缺口
- **WHEN** 补查结束后某项义务仍无合法依据或只有有限结果
- **THEN** 最终 coverage 继续显示 `insufficient/partial` 和剩余 gap，不因已执行过补查而标为 completed

#### Scenario: 补查再综合失败
- **WHEN** 首次回答已通过服务端校验，但补查后的最终回答模型不可用或输出非法
- **THEN** 系统返回首次合法 answer/points/Citation/coverage/basis 并记录补查综合 fallback，不以空结果覆盖它
