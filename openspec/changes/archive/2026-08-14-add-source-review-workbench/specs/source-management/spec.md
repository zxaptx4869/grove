## ADDED Requirements

### Requirement: Source 审阅状态
系统 MUST 为 Source 提供独立于处理状态的审阅状态，取值为待确认、部分确认、已处理；审阅状态 MUST 根据该 Source 当前候选的决策结果派生。

#### Scenario: 处理完成后待确认
- **WHEN** Source 处理成功并产生候选
- **THEN** Source 审阅状态为待确认

#### Scenario: 部分确认
- **WHEN** Source 的候选部分已采纳或已拒绝，但仍有待采纳
- **THEN** Source 审阅状态为部分确认

#### Scenario: 全部处理完成
- **WHEN** Source 的全部候选都已是已采纳或已拒绝
- **THEN** Source 审阅状态为已处理
