## ADDED Requirements

### Requirement: Knowledge Agent 只读工具统一经受控执行入口调用
系统 MUST 让新增结构化查询工具经应用控制的白名单执行入口调用，并使既有知识搜索、Entry 读取与 Evidence 读取能够使用相同的工具版本、可信上下文、状态和审计协议；统一入口 MUST NOT 改变既有已发现集合、Evidence 核验或最终 Citation 边界，也 MUST NOT 接受模型提供的授权范围。

#### Scenario: 结构化查询使用 Run 可信上下文
- **WHEN** Worker 调用 `query_entries` 或 `aggregate_entries`
- **THEN** 执行入口从 Run 注入 owner、Workspace 和可选项目范围，工具参数中不存在可由模型覆盖的范围字段

#### Scenario: 既有 Evidence 工具接入统一状态
- **WHEN** 既有 read_evidence 在批量读取中出现部分不可用对象
- **THEN** 调用继续遵守发现集合与原文核验规则，并使用统一 partial 状态和有界审计摘要，不因适配执行入口放宽读取权限

#### Scenario: 模型请求未注册工具
- **WHEN** 计划或后续控制器输出不在服务端白名单中的工具名
- **THEN** 执行入口记录 denied 并拒绝调用，不通过动态导入、反射或名称猜测执行代码
