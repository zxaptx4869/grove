# native-knowledge-agent-candidate-draft Specification

## Purpose
TBD - created by archiving change add-knowledge-agent-candidate-drafting. Update Purpose after archive.
## Requirements
### Requirement: 原生端候选内容保持只读边界
原生 App MUST 将 dialogue candidate 作为未应用的只读建议展示，不提供固定“整理成知识”、草稿编辑、Candidate 创建或确认写入入口；共享 Candidate 服务与其他端调用方不受影响。

#### Scenario: 展示未应用候选
- **WHEN** 正式 dialogue blocks 包含 candidate 或 candidate_text_only
- **THEN** 移动端标识为 AI 候选/未应用并允许阅读，不显示保存、确认或写入正式知识的操作

