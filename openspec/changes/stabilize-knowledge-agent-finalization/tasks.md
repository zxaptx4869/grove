## 1. 历史与输入门禁

- [x] 1.1 将每轮历史改为从结构化回答块、工具事件和完成状态生成，排除 Entry 正文与 Evidence 原文，并保留结论、建议、决定、授权顺序和未完成步骤
- [x] 1.2 实现单轮 1200 字符回答摘要与整体 5000 token 目标的确定性分级压缩，必要上下文仍超过硬上限时保留准确停止状态
- [x] 1.3 调整软阈值策略，使本轮第一次 9000–12000 正常请求可派发、后续请求达到 9000 时无条件进入收尾，并保持全部冻结预算数值不变

## 2. 收尾隔离与续执行

- [x] 2.1 建立不注册任何资料工具的独立 finalizer，共用既有 `DialogueAnswer`、授权引用与一次收尾请求边界
- [x] 2.2 检测并拒绝 finalizer 的资料工具调用，记录 `finalize_tool_attempted`，确保工具执行为零且不追加模型请求
- [x] 2.3 保存包含问题、指代、授权范围、可恢复材料和指纹的 finalize-only continuation，并实现 Workspace、对象、来源关系与材料有效性复验
- [x] 2.4 实现“继续”只调用 finalizer、成功后清理、主题切换清理和材料失效转重新核验，不重复成功搜索或读取
- [x] 2.5 将 `model_only` 回答依据传入 finalizer 和输出校验，过滤历史资料工具、授权集合与 Entry/Evidence 引用
- [x] 2.6 为无资料最终回答失败保存最小 answer-only continuation，支持“继续”和“下一轮继续”只重试回答

## 3. 工作台状态与离线回归

- [x] 3.1 更新工作台公开完成状态和前端文案，准确区分来源已取得但分析未完成、非法工具尝试、输出失败、超时、系统故障与材料失效
- [x] 3.2 补充四轮现场、历史压缩、软硬阈值、无工具 finalizer、续执行保存/恢复/清理/失效及预算常量测试
- [x] 3.3 运行第三批授权集合、搜索去重、位置指代、Workspace/目录/统计/正文/候选稿只读回归，修复本 change 引入的问题
- [x] 3.4 补充离线回归，验证无资料收尾不引用历史 Evidence、失败可续执行且不重复资料读取；工作台真实现场仍待用户验收

## 4. 验证与交付

- [x] 4.1 在业务代码修改前运行 `openspec validate --all --strict` 并修复工件问题（61 项通过）
- [x] 4.2 运行受影响后端测试与 Ruff、实验工作台前端测试/lint/build、`git diff --check` 和收尾全库 OpenSpec 严格校验
- [x] 4.3 将实现与真实自动化结果记录到本 change，按可验证阶段完成中文 Conventional Commits 本地提交
- [ ] 4.4 由用户在实验工作台重走甲醛四轮对话及失败后“继续”，核对序号、可信度分析、工具隔离、材料复用、相关性隐藏与候选稿只读
- [ ] 4.5 用户明确批准后再同步规格并归档；本任务不得执行归档、推送或合并

## 自动化验证记录（2026-09-10）

- 业务代码修改前：`openspec validate --all --strict` 通过，61 passed、0 failed。
- 后端：`backend/.venv/bin/ruff check backend` 通过；对话循环、工作台、共享只读工具、结构化查询、Entry 搜索、候选稿、API、续聊、结果协议、目录/统计/正文与 Workspace 隔离共 298 个测试通过。
- Python 静态编译：`backend/.venv/bin/python -m compileall -q app evals tests` 通过。
- 前端：工作台 10 个 Vitest 测试通过；`npm run build` 通过；`npm run lint` 为 0 error，保留 `DirectoryDraftDialog.tsx` 两条与本 change 无关的既有 Hook dependency warning。
- 收尾：`git diff --check` 通过；全库 `openspec validate --all --strict` 再次通过，61 passed、0 failed。
- 预算：离线测试断言软阈值 9000、硬上限 12000、文本请求 12、工具 8、Entry 30、Evidence 20、单轮 120 秒、批次文本 192 和向量 64 均未提高。
- 边界：以上 FunctionModel 与离线回归只证明历史、工具、授权、续执行和状态合同，不证明真实模型对自然语言指代及可信度回答质量已经通过；未运行真实模型评测，也未勾选人工验收。
- 本次缺口回归（2026-09-10）：新增 `model_only` finalizer 历史过滤、非法历史 Evidence 拒绝、answer-only continuation 保存/快照脱敏、“下一轮继续”只重试回答和零资料工具调用测试；定向对话循环测试通过。
- 前端提示更新为同时接受“继续”和“下一轮继续”；工作台 Vitest 139 个测试、TypeScript/Vite build 通过，ESLint 0 error，保留 `DirectoryDraftDialog.tsx` 两条既有 Hook dependency warning。
- 后端受影响测试单独运行通过；全文件串行运行时，既有 `_seed_finalize_material` 使用 `id(state)` 生成用户名，在长测试进程中可能因 Python 对象地址复用触发 SQLite 唯一键冲突，单测重跑通过，未将该测试夹具问题归入本次业务回归。

## 工作台人工验收清单

- [ ] 重启实验工作台后依次输入“甲醛是什么”→“好的，帮我解释这些等级标准的具体内容”→“第二个等级信息可信吗”→“那第一条呢，可信吗”。
- [ ] 核对授权列表顺序保持稳定，“第一条”仍对应国标 ENF；回答说明来源性质、可支持范围与缺少的外部核验，不把已有来源说成已完成官方交叉验证。
- [ ] 检查第四轮首次完整请求处于 9000–12000 时仍可派发；进入 finalize 后不再执行 `read_evidence`、搜索、目录或正文读取工具。
- [ ] 人为复现 Evidence 已取得但最终回答输出非法或超时，确认状态显示“来源已取得，可信度分析尚未完成”，且确实提供可用的“继续”。
- [ ] 输入“继续”，确认只重试最终回答，不重复成功搜索、Entry 或 Evidence 读取；完成后再次“继续”不会重复旧任务，材料失效时明确转为重新核验。
- [ ] 核对间接和不相关记录仍不展示；请求候选修改稿时仍只输出“尚未写入”的文本，不修改正式 Entry。
