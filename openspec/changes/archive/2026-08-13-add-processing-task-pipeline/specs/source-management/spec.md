## ADDED Requirements

### Requirement: Source 处理状态与触发
Source MUST 有处理状态（等待处理 / 处理中 / 已完成 / 失败）；采集后 MUST 默认为等待处理；来源列表 MUST 展示状态，并对等待处理提供「开始处理」、对失败提供「重试」。

#### Scenario: 采集后等待处理
- **WHEN** 用户采集一个 Source
- **THEN** Source 状态为等待处理

#### Scenario: 展示状态
- **WHEN** 用户查看来源列表
- **THEN** 每条 Source 展示其处理状态

#### Scenario: 开始处理
- **WHEN** 用户对等待处理的 Source 点击「开始处理」
- **THEN** Source 进入处理流程，状态变为处理中

#### Scenario: 失败重试
- **WHEN** 用户对失败的 Source 点击「重试」
- **THEN** Source 重新进入处理流程
