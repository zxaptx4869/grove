## MODIFIED Requirements

### Requirement: 幂等与不覆盖

系统 MUST 保证重试不复制 Source；处理中的任务 MUST NOT 被并发重复执行；旧处理结果 MUST NOT 被静默覆盖；对已有任务重复触发 MUST NOT 破坏当前状态或产生重复执行。采集幂等命中后客户端仍会再次触发处理，该路径 MUST 复用同一个任务：处理中或已完成的来源 MUST 返回 409 且任务与 Source 状态不变，等待处理的来源 MUST 保持等待处理。

#### Scenario: 重试不复制 Source
- **WHEN** 对失败任务重试
- **THEN** Source 仍只有一条，不新增 Source

#### Scenario: 处理中不可重复触发
- **WHEN** 任务处于处理中
- **THEN** 再次触发不创建重复执行

#### Scenario: 已完成不可重复触发
- **WHEN** 采集幂等命中返回已存在 Source，客户端再次触发处理，而该来源的任务已完成
- **THEN** 请求失败（409），任务与 Source 状态不变

#### Scenario: 等待处理重复触发保持幂等
- **WHEN** 采集幂等命中返回已存在 Source，客户端再次触发处理，而该来源的任务处于等待处理
- **THEN** 该来源仍只有一个等待处理任务，不创建第二个任务、不重复执行、状态保持等待处理
