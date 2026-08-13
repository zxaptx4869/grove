# processing-task Specification

## Purpose
TBD - created by archiving change add-processing-task-pipeline. Update Purpose after archive.
## Requirements
### Requirement: ProcessingTask 与 Source 关联
系统 MUST 提供 `ProcessingTask` 模型并归属一个 Source；一个 Source 在同一时间至多有一个处理任务；任务 MUST 记录状态、步骤、错误与重试次数。

#### Scenario: 触发后创建等待处理任务
- **WHEN** 用户对一个 Source 触发处理
- **THEN** 系统创建该 Source 的 ProcessingTask，状态为等待处理，重试次数为 0

#### Scenario: 查询任务
- **WHEN** 查询一个 Source 的处理任务
- **THEN** 返回其 ProcessingTask 的状态、失败步骤、错误与重试次数

### Requirement: 处理状态机
系统 MUST 支持 ProcessingTask 状态为等待处理、处理中、已完成、失败；状态 MUST 按「等待处理 → 处理中 → 已完成 / 失败」流转；失败后 MUST 可重试并回到处理中。

#### Scenario: 正常处理
- **WHEN** Worker 领取一个等待处理的任务并处理成功
- **THEN** 任务状态变为已完成

#### Scenario: 处理失败
- **WHEN** Worker 处理任务时失败
- **THEN** 任务状态变为失败，并记录失败步骤与错误

#### Scenario: 失败重试
- **WHEN** 用户对失败任务发起重试
- **THEN** 任务状态回到处理中，重试次数加一，并重新进入处理流程

### Requirement: 异步 Worker
系统 MUST 在应用启动后运行一个进程内异步 Worker，轮询数据库中的等待处理任务并执行；处理 MUST NOT 阻塞采集请求。

#### Scenario: 后台处理
- **WHEN** 存在等待处理的任务
- **THEN** Worker 异步领取并处理，采集请求不被阻塞

### Requirement: Provider 边界
系统 MUST 通过 `ProcessingProvider` 抽象执行处理；默认使用 Demo 实现（确定性）；未接入的真实 Provider MUST 明确报错。

#### Scenario: Demo 处理
- **WHEN** 配置为 Demo Provider
- **THEN** 处理确定性完成，不依赖外部服务

#### Scenario: 未接入 Provider 报错
- **WHEN** 使用未接入的真实 Provider
- **THEN** 处理明确报「未接入」，而不是静默成功

### Requirement: 幂等与不覆盖
系统 MUST 保证重试不复制 Source；处理中的任务 MUST NOT 被并发重复执行；旧处理结果 MUST NOT 被静默覆盖。

#### Scenario: 重试不复制 Source
- **WHEN** 对失败任务重试
- **THEN** Source 仍只有一条，不新增 Source

#### Scenario: 处理中不可重复触发
- **WHEN** 任务处于处理中
- **THEN** 再次触发不创建重复执行

