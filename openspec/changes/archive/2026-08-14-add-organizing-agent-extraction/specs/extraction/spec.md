## ADDED Requirements

### Requirement: Extraction 归属与版本化
系统 MUST 提供 `Extraction` 模型并归属一个 Source；一次处理尝试 MUST 生成一条 Extraction，记录模型、提示版本、结构化输出、错误与状态；历史 Extraction MUST 保留，不得被静默覆盖。

#### Scenario: 成功生成 Extraction
- **WHEN** 处理一个 Source 成功
- **THEN** 生成一条状态为 active 的 Extraction，并记录模型与生成时间

#### Scenario: 失败生成 Extraction
- **WHEN** 处理一个 Source 失败
- **THEN** 生成一条状态为 failed 的 Extraction，并记录错误信息

### Requirement: Candidate 归属与候选分类
系统 MUST 提供 `Candidate` 模型并归属一个 Extraction；Candidate MUST 区分为推荐候选与其他发现；无效内容 MUST NOT 落为 Candidate，只在 Extraction 上记录数量与原因摘要。

#### Scenario: 推荐候选与其他发现
- **WHEN** Agent 从 Source 提取出可独立理解的内容
- **THEN** 按推荐候选或其他发现分别落为 Candidate

#### Scenario: 无效内容不落候选
- **WHEN** Agent 判定某段内容为无效
- **THEN** 不创建 Candidate，Extraction 记录丢弃数量与原因摘要

### Requirement: Candidate 结构化字段
Candidate MUST 至少包含标题、核心内容、主类型、信息性质、适用条件、补充说明、证据引用、推荐理由与风险信号；主类型 MUST 为知识、方法、参数或提醒之一。

#### Scenario: 结构化候选字段
- **WHEN** Agent 生成一条候选
- **THEN** 候选包含标题、核心内容、主类型、信息性质、证据引用、推荐理由与风险信号

### Requirement: 证据引用
候选 MUST 通过 `attachment_id` 与原文/OCR 文本片段引用证据，不得仅输出无法定位的自由文本。

#### Scenario: 候选可追溯到附件
- **WHEN** Agent 生成候选
- **THEN** 每条候选的证据引用包含附件 ID 与原文/OCR 片段

### Requirement: Organizing Agent 结构化输出
系统 MUST 通过 PydanticAI Agent 生成结构化 ExtractionDraft；文字附件 MUST 直接进入文本上下文，图片附件 MUST 先由视觉模型 OCR 成文本，再交给文本 Agent 生成候选。

#### Scenario: 文字输入
- **WHEN** Source 包含文字附件
- **THEN** 文字内容进入 Organizing Agent 文本上下文

#### Scenario: 图片输入经 OCR
- **WHEN** Source 包含图片附件
- **THEN** 先调用视觉模型 OCR，OCR 文本再进入 Organizing Agent 文本上下文

### Requirement: 视觉解析与整理解耦
图片 OCR MUST 作为独立服务步骤执行，MUST NOT 由 Organizing Agent 在自主循环中隐式调用；处理流程 MUST 对每个步骤可观察。

#### Scenario: OCR 独立于 Agent 决策
- **WHEN** 处理图片 Source
- **THEN** OCR 由处理服务显式执行，并记录在 Extraction 中，不依赖 Agent 的自主工具调用

### Requirement: 幂等与版本化
重试 MUST NOT 复制 Candidate；新成功 Extraction MUST 成为 active，之前成功 Extraction MUST 变为 superseded；失败 MUST 保留上一份 active 及其 Candidate。

#### Scenario: 再次成功处理不复制候选
- **WHEN** 系统对同一 Source 再次成功生成新的 Extraction
- **THEN** 新 Extraction 成为 active，旧候选不再作为当前候选返回，不新增重复记录

#### Scenario: 重试失败保留上一份
- **WHEN** 对已有成功候选的 Source 重试但失败
- **THEN** 上一份 active Extraction 及其 Candidate 保持不变
