## MODIFIED Requirements

### Requirement: EntrySetSpec 只能表达受限正式知识集合

系统 MUST 使用版本化 `EntrySetSpec` 表达结构化查询集合；集合授权范围 MUST 只来自 Run 固化的 owner、Workspace 和可选项目，模型或客户端 MUST NOT 传入或扩大范围。集合允许可选项目名称筛选，该名称仅在 Run 授权范围内由服务端唯一解析为子集，未知、重名或越界名称 MUST 显式拒绝，不得静默去掉项目条件。集合还允许受控语义查询、`main_type`、`info_nature`、UTC `updated_at` 闭开区间和白名单排序字段，未知字段、运算符、对象标识或 SQL 片段 MUST 被拒绝并留痕。

#### Scenario: 项目范围执行结构化筛选
- **WHEN** 项目范围 Run 的合法计划筛选 `info_nature=experience` 和最近更新时间区间
- **THEN** 系统只查询该项目内满足条件的正式 Entry，不读取同 Workspace 其他项目对象

#### Scenario: 模型尝试指定 Workspace 或项目
- **WHEN** 计划输出包含 Workspace id、项目 id、目录 id、Entry id 或其他授权范围参数
- **THEN** 服务端拒绝非法计划并记录原因，不执行被扩大或改变的范围

#### Scenario: 查询包含未知表达式
- **WHEN** 计划使用未知字段、自由 SQL、正则、任意函数或不受支持的运算符
- **THEN** 服务端不静默删除核心条件或尽量执行，而是将计划判为非法并进入显式降级路径

#### Scenario: Workspace 中指定项目名称
- **WHEN** 用户在 Workspace 对话中指定一个唯一可见项目
- **THEN** 工具只查询该项目子集，Run 的授权范围不变，快照保存实际项目范围

#### Scenario: 全部知识的默认类型
- **WHEN** 用户询问全部知识或正式记录总数，没有明确限定知识类型
- **THEN** 计划不添加 knowledge 单类型条件；只有明确要求知识类型时才限定该类型

### Requirement: aggregate_entries 直接对共享集合执行聚合

`aggregate_entries` MUST 直接对共享集合执行 `count` 或受限 `group_count`，不得从已经被 `entries.limit` 截断的列表反推总数。分组字段 MUST 限定为 `project`、`main_type`、`info_nature` 和 UTC `updated_month`；空 `info_nature` MUST 规范化为 `unspecified`，分组桶数量和序列化体积 MUST 受服务端预算限制。

#### Scenario: 精确计数和列表共享筛选
- **WHEN** 一个无语义条件的计划对相同类型和时间范围请求 count 与最近五条 entries
- **THEN** count 查询覆盖完整授权集合，entries 只返回五条，系统分别表达总数完整性和列表展示上限

#### Scenario: 按月份分组
- **WHEN** 合法计划请求按 `updated_month` 分组计数
- **THEN** SQLite 与 MySQL 8 都按 UTC 年月生成稳定 `YYYY-MM` 桶与计数，并使用确定性桶顺序

#### Scenario: 分组桶达到上限
- **WHEN** group_count 结果超过服务端桶数或字节上限
- **THEN** 系统停止扩张、标记 limited 并显示截断边界，不静默丢桶后仍宣称完整

#### Scenario: 按项目统计
- **WHEN** 用户要求每个项目分别多少条
- **THEN** 系统直接对授权集合按项目聚合，桶含服务端项目标识、名称和数量，包括集合范围内零条项目；同名项目不合并，超预算继续 limited
