# api-time-serialization Specification

## Purpose
TBD - created by archiving change unify-api-time-and-source-status. Update Purpose after archive.
## Requirements
### Requirement: 响应 datetime 统一按 UTC 带偏移输出

后端对外 JSON 响应中的全部 `datetime` 字段 MUST 归一化为 UTC 后输出，串 MUST 带时区偏移（`Z` 或 `+00:00`），MUST NOT 输出不带时区的裸串。归一化口径 MUST 覆盖 `app/schemas/` 下全部模型，不只来源相关模型，且 MUST 集中在同一处实现，新增 schema 字段自动适用同一口径。不带时区的 naïve 值 MUST 按 UTC 解释（开发 SQLite 的 `CURRENT_TIMESTAMP` 与生产 MySQL 已核对的存量值都是 UTC），带偏移的值 MUST 换算到 UTC 后输出。判定 MUST 基于字段类型，MUST NOT 依赖字段名或端点白名单。

#### Scenario: 不带时区的时间按 UTC 输出带 Z

- **WHEN** 来源详情返回 `created_at="2026-09-29T07:23:51"`（数据库中的 UTC 值，驱动取回时不带偏移）
- **THEN** 响应 JSON 中该字段为 `"2026-09-29T07:23:51Z"`，客户端按 UTC 解析得到 15:23（东八区）

#### Scenario: 带偏移的时间换算为 UTC

- **WHEN** 某个响应字段的值为 `2026-09-29T15:23:51+08:00`
- **THEN** 响应 JSON 中该字段为 `"2026-09-29T07:23:51Z"`

#### Scenario: 口径覆盖全部 schema 而非单一端点

- **WHEN** 分别请求来源、项目、条目、对话与知识 Agent Run 等不同响应模型
- **THEN** 所有响应中的 `datetime` 字段都带偏移，任一端点都不出现裸串

#### Scenario: 嵌套模型的字段同样归一化

- **WHEN** 响应模型包含嵌套模型或模型列表（如分页结果里的来源条目）
- **THEN** 嵌套层的 `datetime` 字段同样带偏移输出

#### Scenario: 已带偏移的串不被二次偏移

- **WHEN** 客户端拿到已带 `Z` 的时间串并按现有「缺时区才补 Z」逻辑解析
- **THEN** 检测到已带偏移后跳过补位，解析结果与后端值一致，不产生 8 小时二次偏移

### Requirement: 时间解析与序列化异常可观测

时间字段的归一化与序列化异常 MUST 留下可观测日志（至少 warning 级、含异常堆栈与字段或值信息），并 MUST 向上抛出使校验失败，MUST NOT 静默返回裸串或错误值把问题掩盖成「看起来正常」的响应。

#### Scenario: 归一化失败时记录日志并失败

- **WHEN** 某个 `datetime` 字段的时区信息在归一化时抛错
- **THEN** 服务端记录含堆栈的 warning 日志，该字段校验失败，响应不返回未经归一化的值

#### Scenario: 无法解析为时间时暴露校验错误

- **WHEN** 响应模型字段收到既不是 `datetime` 也无法解析为时间的值
- **THEN** 校验失败并保留字段路径与原始值，便于定位是数据源还是序列化层的问题，不返回静默替换成的空串

### Requirement: 生产 MySQL 会话时区固定为 UTC

生产 MySQL MUST 以 `default-time-zone='+00:00'` 固定服务端会话时区，MUST NOT 依赖客户端或应用层补偿来消化 8 小时偏差；部署核对 MUST 以 `SELECT @@global.time_zone, @@session.time_zone;` 的结果均为 `+00:00`（或等价的 `UTC`）为准。当会话时区不是 UTC 时，`server_default=func.now()` 写入的会是本地墙钟时间，而应用按 UTC 解释 naïve 值，时间口径即被破坏，核对不通过 MUST 在变更窗口内修正配置而非修改应用假设。

#### Scenario: 核对生产会话时区

- **WHEN** 部署核对执行 `SELECT @@global.time_zone, @@session.time_zone;`
- **THEN** 两项均为 `+00:00`，应用按 UTC 解释数据库返回的 naïve 时间成立

#### Scenario: 会话时区偏离时判定口径破裂

- **WHEN** 核对发现会话时区为 `+08:00` 等非 UTC 值
- **THEN** 判定写入侧会落本地墙钟时间、应用侧 UTC 解释不再成立，按运维项修正 MySQL 配置，不通过客户端偏移补丁掩盖

