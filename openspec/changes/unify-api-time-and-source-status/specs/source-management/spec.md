## MODIFIED Requirements

### Requirement: Source 处理状态与触发

Source MUST 有处理状态（等待处理 / 处理中 / 提取完成 / 失败）；采集后 MUST 默认为等待处理；来源列表 MUST 展示状态，并对失败提供「重试」。等待处理但已存在处理任务的来源由处理 Worker 自动接手，MUST NOT 提供重复触发入口；等待处理且不存在处理任务（`has_processing_task` 为 false）的来源 MUST 显示「处理未启动」并提供「重试处理」。失败重试与未启动重试 MUST 是两个可区分的入口，文案分别为「重试」与「重试处理」，两者 MUST 调用 `POST /api/sources/{id}/process`；服务端 409（正在处理或已处理完成）MUST 视为状态本身正常，只刷新该来源状态，MUST NOT 提示为失败。判定 MUST 依据处理任务存在性，MUST NOT 使用「等待超过 N 秒」等时间阈值启发式。

#### Scenario: 采集后等待处理

- **WHEN** 用户采集一个 Source
- **THEN** Source 状态为等待处理，列表显示「等待处理」

#### Scenario: 展示状态

- **WHEN** 用户查看来源列表
- **THEN** 每条 Source 展示其处理状态，提取完成状态文案为「提取完成」

#### Scenario: 等待处理且已有任务时不重复触发

- **WHEN** 来源状态为等待处理且 `has_processing_task` 为 true
- **THEN** 该行只显示「等待处理」，不显示「开始处理」或「重试处理」

#### Scenario: 处理未启动可识别并重试

- **WHEN** 来源状态为等待处理且 `has_processing_task` 为 false
- **THEN** 该行显示「处理未启动」与可点的「重试处理」，点击后调用 `POST /api/sources/{id}/process` 并刷新状态

#### Scenario: 用任务存在性而非等待时长判定

- **WHEN** 来源已等待处理较长时间但仍有处理任务
- **THEN** 该行仍显示「等待处理」，不显示「处理未启动」

#### Scenario: 失败重试

- **WHEN** 用户对失败的 Source 点击「重试」
- **THEN** Source 重新进入处理流程

#### Scenario: 重复触发被服务端拒绝

- **WHEN** 重试时服务端返回 409（来源正在处理或已处理完成）
- **THEN** 界面不提示失败，只刷新该来源状态

#### Scenario: 处理中与已完成不提供触发入口

- **WHEN** 来源处于处理中或提取完成
- **THEN** 该行不显示「重试」或「重试处理」
