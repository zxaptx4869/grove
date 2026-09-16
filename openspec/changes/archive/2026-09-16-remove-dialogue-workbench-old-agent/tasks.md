## 1. Change 工件与入口收敛

- [x] 1.1 完成 proposal、spec、design、tasks，并通过 `openspec validate --all --strict`。
- [x] 1.2 将 `evals.dialogue_loop` CLI 从 old/new 双臂参数和双副本调度收敛为统一循环单臂入口。
- [x] 1.3 删除实验入口、执行器和报告中仅用于 old 对照的启动、执行、字段和输出；保留统一循环彩排、真实模型验证、隔离和导出。

## 2. 测试与边界回归

- [x] 2.1 迁移实验台后端测试到单臂结果合同，删除只验证旧结构化结果、旧报告和双臂资源的测试。
- [x] 2.2 增加静态回归断言：实验台代码不再调用 `runner.execute_run()`；正式 Web 仍保持 `production_adapter → dialogue_loop`。
- [x] 2.3 运行实验台相关后端测试、dialogue-loop 核心测试、Web Agent 后端测试、前端 typecheck/build/相关测试，并检查移动端无改动。
- [x] 2.4 运行 `git diff --check`，记录真实模型人工验收仍待用户执行，不把自动化结果当作人工验收。
- [x] 2.5 更新实验入口 README，移除已退役 old/new 对照命令和双臂运行说明。

## 3. 本地交付

- [x] 3.1 更新任务勾选和验证记录，确认未修改正式 Web、移动端、数据库字段及 dialogue-loop 核心行为。
- [x] 3.2 创建中文 Conventional Commit 本地提交；不推送、不合并、不归档，等待人工验收。

## 4. 验证复核与人工验收

- [x] 4.1 在相同 Python 环境中对当前分支与包含时间字段修复的 `main` 基线运行同一组 Web Agent 测试，记录失败项及归因证据。
- [x] 4.2 复跑实验台、dialogue-loop 核心、生产适配、前端与 OpenSpec 检查，并启动真实模式实验台完成只读健康检查。
- [x] 4.3 由用户在真实模式实验台完成人工语义验收；最新 7 轮真实 DeepSeek 会话均完成，详情及刷新操作证据边界见 validation.md。
