## MODIFIED Requirements

### Requirement: Source 审阅状态
系统 MUST 根据 Source 当前候选的决策结果派生审阅状态；确认台待处理来源 MUST 只展示仍有待采纳候选的来源，并返回待确认或部分确认；全部候选都已是已采纳或已拒绝的来源 MUST 视为已处理，且不再出现在待处理来源列表。

#### Scenario: 处理完成后待确认
- **WHEN** Source 处理成功并产生候选，且候选都未决策
- **THEN** 该来源出现在待处理来源列表，审阅状态为待确认

#### Scenario: 部分确认
- **WHEN** Source 的候选部分已采纳或已拒绝，但仍有待采纳
- **THEN** 该来源出现在待处理来源列表，审阅状态为部分确认

#### Scenario: 全部处理完成
- **WHEN** Source 的全部候选都已是已采纳或已拒绝
- **THEN** 该来源视为已处理，不再出现在待处理来源列表
