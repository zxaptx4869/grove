## 1. 公共运行控制与恢复边界

- [x] 1.1 新建无 answer 编排职责的 Run 取消控制模块，迁移 Worker、production adapter、Candidate、Entry Revision 与搜索调用方，并验证取消异常和短会话检查语义不变
- [x] 1.2 为 Worker 增加 answer Run 恢复白名单：允许当前领取/统一循环安全状态，拒绝旧步骤和未知快照；保留 operation Run 的现有幂等恢复
- [x] 1.3 补充公共取消与历史恢复回归测试，覆盖取消、重试上限、活动槽释放、旧快照不进入统一循环

## 2. 旧执行编排退役

- [ ] 2.1 依据静态调用、动态导入、脚本入口和公开接口核对结果，删除旧 runner、investigation、composite、coverage、shared graph 及只服务于它们的 Agent/服务模块
- [ ] 2.2 清理 dialogue-loop 预检与插桩中的旧模块动态导入，保留当前统一循环实际使用的插桩能力
- [ ] 2.3 保留历史 Run/Investigation API、数据库模型与字段、Alembic 历史迁移和 composite 历史投影，并用读取测试证明兼容

## 3. 测试迁移

- [ ] 3.1 删除只验证已退役执行图的测试，并将 Web API、Candidate、Entry Revision、Workspace、权限、幂等与取消测试的旧 runner 夹具迁移到统一循环确定性边界
- [ ] 3.2 运行 dialogue_loop、production_adapter、Worker、实验台、Candidate、Entry Revision 与历史恢复测试，对照实施前 35 项基线失败逐项归因
- [ ] 3.3 运行后端受影响静态检查与测试、`git diff --check`、移动端未改动检查及正式调用链/旧导入静态扫描

## 4. 验证记录与收尾

- [ ] 4.1 运行 `openspec validate --all --strict`，在 change 中记录自动化结果、基线差异、实际兼容残留和未执行的付费模型人工验收
- [ ] 4.2 提供普通问答、搜索后追问、候选稿、Entry Revision、取消与刷新恢复的人工复测清单；不自行调用付费模型
- [ ] 4.3 完成本地阶段提交并报告提交哈希；不推送、不合并、不归档
