## Context

实验评估入口目前在 `evals.dialogue_loop` 中同时维护 old/new 两条臂：old 臂隔离副本后调用旧 `runner.execute_run()`，new 臂调用统一 `dialogue_loop.run_turn()`。交互式 `dialogue_workbench` 已使用统一循环，但仍复用同一套实验模块的对照概念、报告和测试。正式 Web 已由 Worker 通过 `production_adapter` 调用统一循环，本 change 只收敛实验台边界。

## Goals / Non-Goals

**Goals:**

- 单一实验执行入口只创建一个隔离副本并运行统一 dialogue-loop。
- 实验台报告继续记录模型、工具、预算、隔离指纹、轮次结果、失败和导出数据，但不再输出 old/new 对照字段或章节。
- 保持现有真实模型、离线彩排、密码预检、业务数据不变和工作台对话能力。

**Non-Goals:**

- 不修改 `evals.dialogue_loop.loop` 的求解、工具、预算、结果块、句柄或收尾行为。
- 不删除或重构 `runner.py`、investigation、coverage repair、composite、shared execution graph 或数据库迁移字段。
- 不修改正式 Web API、Worker、`production_adapter.py`、Candidate、Entry Revision、Workspace、权限或移动端代码。

## Decisions

1. **保留统一循环实现，删除对照外壳。** 将实验入口、隔离调度、序列化报告和评分从双臂模型改为单一 `run_scenario` 结果；统一循环本身不改写，避免把实验台清理误变成行为迁移。
2. **单副本而非保留空 old 副本。** 每批实验只复制一次 seed 数据库，所有场景顺序复用同一实验副本；这移除旧臂启动逻辑，同时保留当前实验对真实业务库的隔离保证。
3. **报告字段采用单一结果合同。** 结果保留 `scenario`、`turns`、预算、工具和隔离指纹；删除 `arm`、`by_arm`、旧流程章节和旧数据库结论。历史报告继续作为静态文件存在，不由新代码重写。
4. **测试按能力分层。** 保留统一循环和工作台能力测试，新增单臂入口不调用旧 runner 的回归断言；删除仅证明旧结构化结果、旧报告渲染或双臂资源对照的测试。

## Risks / Trade-offs

- [历史报告格式不再由新代码生成] → `regrade` 仅接受新单臂报告；历史双臂 JSON/Markdown 保留为文件，不执行自动迁移。
- [旧评估调用方仍可能存在于归档工件或非实验代码] → 实施后只要求实验入口不再导入/调用 `runner.execute_run()`，并单独报告仓库中仍保留的其他历史调用方。
- [单副本顺序运行会改变旧双臂实验的资源统计] → 报告明确改为单臂总量，预算上限按选择的场景数计算，不宣称与历史双臂批次可比。

## Migration Plan

1. 建立 change 分支并完成 proposal/spec/design/tasks 严格校验。
2. 改写实验入口、执行、报告和对照专用测试；不改正式 Web 或移动端。
3. 运行 OpenSpec、实验台后端、dialogue-loop 核心、Web Agent 后端和前端验证。
4. 本地提交并等待人工实验台/真实模型验收；不推送、合并或归档。

回滚时恢复本 change 的本地提交即可；正式 Web、数据库字段和历史报告不需要回滚。
