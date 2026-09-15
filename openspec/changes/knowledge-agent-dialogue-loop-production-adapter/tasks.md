## 1. 迁移边界与适配接口

- [x] 1.1 对照正式 Conversation/Message/Run 模型和 `dialogue_loop` 的 `LoopState`，列出字段映射与缺口；确认 Web 新入口不调用旧多级规划执行图。
- [x] 1.2 设计并实现生产适配器的状态构造、身份/Workspace 注入和结果转换接口；不引入实验台 JSON 存储。
- [x] 1.3 明确现有正式领域工具、权限校验、取消边界和可观测记录的复用入口，移除同一请求的双重编排路径。

## 2. 正式轮次持久化与恢复

- [x] 2.1 将用户消息、结构化回答块、工具/模型调用、终态和 continuation 摘要写入正式会话模型。
- [x] 2.2 实现活动 Run 的幂等、取消、并发检查和失败收尾；不吞 SQLite/数据库锁错误。
- [x] 2.3 实现 continuation 恢复前的 Workspace、用户、项目、目录、Entry 和 Source 复验，并只重试未完成步骤。
- [x] 2.4 明确服务重启时可恢复与不可恢复状态，禁止伪装成 completed。

## 3. 结构化 API 合同

- [x] 3.1 保持 text/list/statistic/entry/evidence/candidate/insufficient 的真实类型映射。
- [x] 3.2 保持 completed/partial_completed/not_executed/unsupported/failed 与 can_continue 的程序语义。
- [x] 3.3 验证空结果在查询已成功时正常完成，非法参数和工具失败保留准确缺口。
- [x] 3.4 验证候选稿只返回候选，不写入正式 Entry，并记录 provider/model/fallback。

## 4. 确定性验证与人工验收入口

- [x] 4.1 增加无真实模型的适配器、状态映射、结果类型、隔离、幂等和 continuation 测试。
- [x] 4.2 增加 API 短链路彩排：身份、项目列表、主题搜索、列表位置追问、当前 Entry 补充、候选稿。
- [x] 4.3 运行后端相关测试、静态检查和 `openspec validate --all --strict`；记录实验台行为与正式 API 行为的差异。
- [ ] 4.4 在适配器自动验证完成后停止，交由用户进行真实模型人工验收；本任务不接入 Web 页面。
