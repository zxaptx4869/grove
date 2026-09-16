# knowledge-agent-dialogue-workbench-unified Specification

## Purpose
规定实验台统一使用 dialogue-loop 的执行、隔离、报告与导出合同，移除旧 Agent 对照入口，同时保持正式 Web 与移动端边界不变。
## Requirements
### Requirement: 实验台只运行统一 dialogue-loop

实验台 SHALL 只通过统一 `dialogue_loop` 执行每个场景和轮次，不得导入或调用 `knowledge_agent.runner.execute_run()`，也不得向用户暴露 old/new 对照选择。

#### Scenario: 运行真实或离线实验

- **WHEN** 用户启动实验台预检、彩排或真实实验
- **THEN** 系统为实验批次创建一个隔离数据库副本，并由统一 dialogue-loop 顺序执行所选场景
- **AND** 系统不创建 old/new 双副本、不启动旧 Agent 臂、不调用 `runner.execute_run()`

#### Scenario: 统一循环验证保留

- **WHEN** 实验台完成一轮对话
- **THEN** 系统继续记录统一循环产生的回答、结果块、工具调用、模型调用、预算、完成状态和可继续信息
- **AND** 现有 Workspace、权限、只读工具和真实模型配置边界保持不变

### Requirement: 实验台报告不再输出旧对照内容

实验台 SHALL 输出单一统一循环结果合同；报告不得包含 old/new 选择、双臂资源汇总、旧流程章节或仅用于旧流程的数据库结论。

#### Scenario: 生成实验报告

- **WHEN** 实验批次完成、停止或发生基础设施异常
- **THEN** 报告包含场景、轮次、统一循环结果、预算、隔离指纹、失败诊断和导出路径
- **AND** 报告不包含 `arm`、`by_arm`、旧流程/新循环对照章节

#### Scenario: 离线彩排与重评

- **WHEN** 用户执行无模型彩排或对已保存报告进行重评
- **THEN** 彩排和重评使用同一单臂结果合同，不启动旧 Agent，不需要 old/new 参数

### Requirement: 正式 Web 与移动端边界保持不变

本实验台 change MUST NOT 改变正式 Web Agent 的 `Worker → production_adapter → dialogue_loop` 执行链，也 MUST NOT 修改移动端调用路径。

#### Scenario: 正式 Web 回归检查

- **WHEN** 运行 Web Agent 后端测试或静态检查
- **THEN** 普通 answer Run 仍由 Worker 进入 `production_adapter` 并调用统一 dialogue-loop
- **AND** Candidate、Entry Revision、Workspace、权限和数据库字段合同保持不变

#### Scenario: 移动端现状

- **WHEN** 检查移动端知识 Agent 客户端
- **THEN** 其现有 `/api/knowledge-agent` 调用保持原样
- **AND** 本 change 不新增、删除或迁移移动端代码
