## MODIFIED Requirements

### Requirement: Organizing Agent 结构化输出
系统 MUST 通过 PydanticAI Agent 生成结构化 ExtractionDraft；ExtractionDraft MUST 包含 source_title；文字附件 MUST 直接进入文本上下文，图片附件 MUST 先由视觉模型 OCR 成文本，再交给文本 Agent 生成候选；处理成功后 MUST 用 source_title 更新 Source 标题。

#### Scenario: 文字输入
- **WHEN** Source 包含文字附件
- **THEN** 文字内容进入 Organizing Agent 文本上下文

#### Scenario: 图片输入经 OCR
- **WHEN** Source 包含图片附件
- **THEN** 先调用视觉模型 OCR，OCR 文本再进入 Organizing Agent 文本上下文

#### Scenario: 生成标题
- **WHEN** Organizing Agent 处理成功
- **THEN** 输出非空 source_title，并用于更新 Source 标题
