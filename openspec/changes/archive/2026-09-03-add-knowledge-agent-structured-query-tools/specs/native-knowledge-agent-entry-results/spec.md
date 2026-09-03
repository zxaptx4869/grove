## MODIFIED Requirements

### Requirement: 原生对话明确区分综合回答与 Entry 查找结果
原生 App MUST 根据 Run 的实际结果形态渲染综合回答或结构化 Entry 结果；Entry 结果 MUST 使用服务端确认的筛选/统计块、正式知识对象卡和列表标题，不显示“综合回答”正文，也不把计划、聚合、排序结果或匹配说明标成 Citation。Workspace 范围 MUST 逐项展示项目归属，所有结果保留生成时范围和完整性说明。

#### Scenario: 自动返回 Entry 列表
- **WHEN** `actual_result_mode=entries` 的 Run 成功完成且只有 Entry 列表输出
- **THEN** thread 显示“找到 N 条相关知识”及 Entry 卡列表，不先输出一段重复的综合描述

#### Scenario: 自动返回综合回答
- **WHEN** `actual_result_mode=answer`
- **THEN** App 继续使用现有结构化回答、引用、调查摘要与冲突界面，不混入 Entry 结果卡语义

#### Scenario: Workspace 跨项目结果
- **WHEN** 结果来自 Workspace 全部知识且包含多个项目
- **THEN** 每张卡显示项目与目录，列表头不把某一个项目误标为整个结果范围

#### Scenario: 自动返回统计与 Entry 列表
- **WHEN** `actual_result_mode=entries` 的 v2 结果包含 count、group_count 和 entries
- **THEN** thread 先展示结构化范围/筛选与统计，再展示排序说明和 Entry 卡，不生成重复 AI 综合正文

## ADDED Requirements

### Requirement: 原生端按完整性展示结构化筛选与聚合
原生 App MUST 根据服务端 v2 结构化字段展示有界筛选摘要、精确计数、分组桶、排序和警告；客户端 MUST NOT 从 Entry 卡数量自行推断总数或重新计算聚合。只有 count 完整性为 `complete` 时才能显示“共 N 条”，`limited` 或 `unknown` MUST 使用“本次匹配到”等边界文案并显示可能不完整或执行异常。

#### Scenario: 精确计数与最近五条
- **WHEN** 服务端返回 complete count=23 和按更新时间倒序的五条 Entry
- **THEN** 界面显示“共 23 条”及“最近更新 5 条”，不把五张卡误写成总数

#### Scenario: 有限语义统计
- **WHEN** count 来自包含 semantic_query 的 limited 集合
- **THEN** 界面说明统计只覆盖本次匹配结果，不显示“全部 23 条”或其他精确全集语义

#### Scenario: 分组包含未标注信息性质
- **WHEN** group_count 返回 `info_nature=unspecified` 桶
- **THEN** App 使用“未标注”用户文案并显示服务端计数，不暴露内部枚举或丢弃该桶

#### Scenario: 聚合块过长
- **WHEN** 分组结果达到服务端桶上限或在目标视口不能一次展示完
- **THEN** 组件保持有界滚动/展开和截断提示，不造成横向溢出或遮挡 Composer

### Requirement: 原生端兼容 v1/v2 历史结果并保持当前对象复验
原生 App MUST 同时解析旧 v1 Entry 结果和新增 v2 查询结果；缺少计划、筛选或聚合字段时 MUST 保持既有列表、空结果、分页与纠正形态体验。v2 历史统计保持生成时快照，Entry 卡详情仍重新读取当前对象并显示已更新或当前不可用。

#### Scenario: 恢复旧 v1 结果
- **WHEN** 历史 Run 只有 v1 query、items 和 completeness
- **THEN** App 按现有 Entry 列表渲染，不显示空统计区域、未知 schema 错误或猜测筛选条件

#### Scenario: 恢复 v2 组合结果
- **WHEN** App 重启后加载包含结构化计划摘要、聚合和分页 Entry 的 v2 Run
- **THEN** App 恢复相同统计、排序、首屏项和完整性，且不重新提交消息或重跑查询

#### Scenario: v2 Entry 后来变化
- **WHEN** 用户从历史统计结果打开一条后来更新或删除的 Entry
- **THEN** 聚合保持历史快照语义，详情重新鉴权并显示当前内容、已变化或当前不可用
