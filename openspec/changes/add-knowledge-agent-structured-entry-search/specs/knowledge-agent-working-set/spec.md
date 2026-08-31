## MODIFIED Requirements

### Requirement: 无证据结果不得写入工作集项
取消、失败或澄清 Run MUST NOT 创建输出上下文版本；知识不足、回答模型 fallback 或没有有效引用时 MUST NOT 把召回 Entry 写入工作集项。结构化 Entry 查找 Run 无论命中多少结果都 MUST NOT 自动写入工作集项或创建输出上下文版本。`continue` 的综合回答 MUST 保持原活动版本；达到 `completed` 或 `partial` 终态的 `new_topic` 综合回答 MUST 创建仅含主题标签的空版本以承接后续指代，但该标签 MUST NOT 作为事实。事实性回答与可选输出版本 MUST 在同一事务提交。

#### Scenario: 回答被取消
- **WHEN** Run 在任一阶段取消
- **THEN** 当前活动工作集保持不变且不产生半成品版本

#### Scenario: 知识不足
- **WHEN** `continue` 综合回答 Run 没有可核验 Evidence 或最终有效引用为空
- **THEN** 系统不使用召回结果更新工作集项并保持原活动版本

#### Scenario: 新话题知识不足
- **WHEN** `new_topic` 综合回答 Run 明确了新主题但没有有效引用
- **THEN** 系统建立不含 Entry 项的主题版本供下一轮理解指代，且不得把主题标签作为知识事实

#### Scenario: 结构化查找命中多个 Entry
- **WHEN** `actual_result_mode=entries` 的 Run 返回一条或多条正式知识
- **THEN** 系统保留既有活动工作集且不创建输出版本，搜索命中不因展示为对象卡而成为后续事实种子

#### Scenario: 终态事务失败
- **WHEN** 回答、结构化结果或新工作集版本的最终事务提交失败
- **THEN** 系统既不暴露正常助手结果，也不切换活动工作集

