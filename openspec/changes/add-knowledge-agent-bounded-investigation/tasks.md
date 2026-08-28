## 1. 骨架搭建前置：修复连续追问验收遗留

- [x] 1.1 调整有限历史选择，排除当前 Run 的用户消息、当前空助手占位和其他无内容助手占位，同时补足被占位挤掉的有效历史条数
- [x] 1.2 用真实消息提交流程补充历史窗口回归测试，断言实际消息 ID、顺序、内容截断与当前占位排除；运行 `cd backend && .venv/bin/python -m pytest tests/test_knowledge_agent_follow_up.py`
- [x] 1.3 修复跨会话取消测试的 session/engine 资源回收，确保不再出现 aiosqlite 连接被 GC 回收的 warning；运行 `cd backend && .venv/bin/python -m pytest tests/test_knowledge_agent_worker.py -W error`
- [x] 1.4 完成前置修复本地提交，提交信息使用 `fix: 硬化知识 Agent 历史与并发测试`

## 2. 骨架搭建：调查模型、状态与迁移

- [x] 2.1 定义回答模式、调查/轮次/查询状态、停止原因和服务端预算配置，默认最多 3 轮、每轮 3 个查询、总计 6 个不同查询、30 个不同 Entry、12 条 Evidence
- [x] 2.2 新增 Run 一对一 Investigation、Round、Query（或满足设计等价规范的模型），保存所有权、范围/模式/预算快照、当前轮次、规范化查询指纹、增量计数、覆盖/缺口/冲突摘要与恢复时间
- [x] 2.3 扩展 Run、ModelInvocation、ToolCall、Evidence 或关联模型，保存请求/实际回答模式、调查摘要及可选 investigation/round/query 归属；为同调查轮次号和规范化查询建立唯一约束
- [x] 2.4 新增 Alembic 迁移与 downgrade，兼容 SQLite/MySQL 8；旧 Run 保持可读，旧客户端缺省 `answer_mode=auto`
- [x] 2.5 增加枚举、模型默认值、Workspace/用户冗余、唯一约束、级联关系、SQLite 升降级和序列化测试；运行 `cd backend && .venv/bin/python -m pytest tests/test_knowledge_agent_models.py tests/test_knowledge_agent_investigation_models.py`
- [x] 2.6 完成数据骨架本地提交，提交信息使用 `feat: 建立知识 Agent 调查数据骨架`

## 3. 实现：回答模式路由与结构化调查控制器

- [x] 3.1 新增独立回答模式路由 Agent：输入独立问题和受限主题摘要，结构化输出 quick/investigate，配置独立 purpose、prompt 版本、超时与有限重试
- [x] 3.2 实现 `auto` 路由、`quick`/`investigate` 显式覆盖与安全 fallback；路由失败固定选择 quick，并记录 provider/model/fallback/error/耗时
- [x] 3.3 新增结构化调查控制器：只输出 `search`/`answer`/`insufficient`、最多三条文本查询及有长度上限的 coverage/gaps/conflicts/reason，不接受范围、对象 ID、工具名或预算修改
- [x] 3.4 实现控制器输入构建，只传独立问题、可信范围标签、工作集短摘要、已执行查询、紧凑证据账本和剩余预算，不传无限历史或整份 Attachment
- [x] 3.5 增加模式显式覆盖、auto quick/investigate、路由未配置/失败/非法结构、控制器三种动作、越权字段、超长摘要与模型可观测性测试；运行 `cd backend && .venv/bin/python -m pytest tests/test_knowledge_agent_investigation_agents.py`
- [x] 3.6 完成路由与控制器本地提交，提交信息使用 `feat: 增加知识 Agent 调查路由与控制器`

## 4. 实现：调查账本与可信只读工具

- [x] 4.1 实现 Run 内查询规范化/指纹和全局去重；重复查询不执行、不计实际查询数，部分重复只保留合法新查询
- [x] 4.2 实现跨轮次已发现集合：合并复验工作集种子、用户显式引用与各轮搜索结果，按 Entry 去重并在每次读取前重新校验用户、Workspace、项目和正式状态
- [x] 4.3 扩展混合搜索、Entry 读取和 Source Evidence 工具，按 round/query 记录结果归属、增量计数和 partial/empty/error；控制器文本查询不能携带或改变可信范围
- [x] 4.4 实现当前 Run Evidence 跨轮次幂等复用与不同 Evidence 预算，历史 Evidence、助手消息、控制器摘要和搜索片段均不得进入可引用集合
- [x] 4.5 实现紧凑账本重建和序列化：保存 ID、指纹、状态、短摘要、覆盖/缺口/冲突与不可用对象，不复制整份 Entry/Attachment/prompt
- [x] 4.6 增加跨轮发现、同 Entry 多查询命中、相同 Evidence 幂等、对象中途失效、范围越权、候选排除、长原文最小审计和账本重建测试；运行 `cd backend && .venv/bin/python -m pytest tests/test_knowledge_agent_tools.py tests/test_knowledge_agent_investigation_ledger.py`
- [x] 4.7 完成账本与工具本地提交，提交信息使用 `feat: 实现知识 Agent 跨轮证据账本`

## 5. 实现：有界调查编排、预算与停止

- [ ] 5.1 保留现有 quick 单轮执行图，在上下文决策后按 actual answer mode 分支；澄清路径不得创建 Investigation
- [ ] 5.2 实现最多三轮的应用层循环：持久化轮次计划、执行去重后的固定搜索→Entry→Evidence 工具链、提交观察与账本增量，再把结果反馈下一轮控制器
- [ ] 5.3 实现轮次、每轮查询、总查询、不同 Entry 和 Evidence 双层硬预算；客户端/模型无法放大预算，实际预算在 Investigation 创建时固化
- [ ] 5.4 实现稳定停止原因：控制器完成/不足、无合法新查询、无新增 Entry/Evidence、各类预算、取消和失败；预算或无进展停止不得误报为模型 fallback
- [ ] 5.5 实现最终综合：只传当前 Run Evidence 与紧凑账本，返回答案/引用及实际模式、轮数、查询数、停止原因、覆盖、未解决缺口和冲突提示；无证据时 insufficient
- [ ] 5.6 输出工作集只加入最终有效引用实际使用的 Entry；仅被搜索发现的 Entry 不加入，失败/取消不推进
- [ ] 5.7 增加 quick 不受影响、一/多轮补查、控制器主动停止、重复查询、无进展、每种预算停止、多轮引用、未解决缺口、冲突与工作集过滤测试；运行 `cd backend && .venv/bin/python -m pytest tests/test_knowledge_agent_runner.py tests/test_knowledge_agent_investigation_runner.py`
- [ ] 5.8 完成调查编排本地提交，提交信息使用 `feat: 实现知识 Agent 有界自主调查`

## 6. 实现：检查点恢复、取消与终态一致性

- [ ] 6.1 将完成轮次作为事务检查点，恢复时从持久化查询、Entry/Evidence 和轮次摘要重建账本与剩余预算
- [ ] 6.2 对未完成轮次实现安全重置或幂等重放；恢复不得重复轮次号、查询、Evidence、助手回答或预算计数
- [ ] 6.3 在回答模式路由、控制器调用、每个查询工具批次、Evidence 读取和最终综合前后使用独立短会话检查取消
- [ ] 6.4 取消时保留已提交轮次供审计，原子更新 Run/Investigation 取消状态和活动槽；丢弃未提交模型/工具结果且不生成正常回答或工作集
- [ ] 6.5 将助手消息、Run/Investigation 终态与摘要、活动槽和可选工作集放入最终一致事务；提交失败可按租约恢复
- [ ] 6.6 增加各阶段崩溃、完成两轮后恢复、未完成轮幂等重放、跨事务取消、迟到结果、最终事务回滚与两个 Worker 竞争测试；运行 `cd backend && .venv/bin/python -m pytest tests/test_knowledge_agent_investigation_recovery.py tests/test_knowledge_agent_worker.py -W error`
- [ ] 6.7 完成恢复与取消本地提交，提交信息使用 `feat: 支持知识 Agent 调查恢复与取消`

## 7. 实现：API、进度与可观测性

- [ ] 7.1 扩展消息提交 schema/API 接收默认 `auto` 的 `answer_mode`；相同 `client_message_id` 重试始终返回首次请求模式和 Run，不因新载荷改变
- [ ] 7.2 扩展 Run/消息响应，返回请求/实际回答模式、current_step/current_round、完成轮数、查询数、停止原因、覆盖/缺口/冲突和降级摘要
- [ ] 7.3 新增按 Run 读取逐轮调查详情的只读接口，实施用户、Workspace、对话和项目范围 404 校验、分页/数量与文本长度限制
- [ ] 7.4 扩展 ModelInvocation/ToolCall 写入与观测接口，记录 `investigation_route`、逐轮 controller/embedding/rerank/tool、最终 synthesis 的 provider/model/fallback/error/耗时和 round/query 归属
- [ ] 7.5 扩展 current_step 提交为 `investigation_route`、`round_plan`、`round_search`、`round_evidence`、`synthesize` 并确保其他会话可实时轮询
- [ ] 7.6 增加旧客户端默认值、三种模式、幂等、逐轮详情、运行中进度、降级汇总、正常 empty、不足/partial、取消和跨 Workspace/用户隔离 API 测试；运行 `cd backend && .venv/bin/python -m pytest tests/test_knowledge_agent_api.py tests/test_knowledge_agent_investigation_api.py tests/test_ai_observability_api.py`
- [ ] 7.7 完成 API 与可观测性本地提交，提交信息使用 `feat: 暴露知识 Agent 调查进度与摘要`

## 8. 验证：自动化、SQLite 与真实 MySQL

- [ ] 8.1 运行完整后端测试和静态检查且无 warning：`cd backend && .venv/bin/python -m pytest -W error && .venv/bin/ruff check app tests`
- [ ] 8.2 在全新与已有 SQLite 数据库执行 Alembic upgrade/downgrade/upgrade，验证默认模式、唯一约束、级联关系和旧 Run 兼容
- [ ] 8.3 用真实 API 走查 quick、auto→quick、auto→investigate、强制 investigate、两轮补查、无进展、预算停止、多轮引用、幂等、取消和崩溃恢复，并把 curl、状态码、轮次账本和停止摘要记录到 `docs/验收记录/add-knowledge-agent-bounded-investigation-curl.md`
- [ ] 8.4 在可用 MySQL 8 环境验证迁移、同调查查询/轮次唯一约束、逐轮事务提交、跨事务取消、租约恢复与最终事务一致性，并把环境和结果写入同一验收记录
- [ ] 8.5 运行 `openspec validate --all --strict`，逐项核对实现与 proposal、design、六份 delta specs、两个权威产品专题一致

## 9. 收尾：评审、遗留与归档

- [ ] 9.1 检查本 change 没有引入联网、知识写入、客户端 UI、任意工具循环或跨 Run 事实记忆，并完成安全/隔离/证据边界代码复核
- [ ] 9.2 向用户逐条说明遗留问题、背景和影响；仅在用户同意后登记到 `docs/discussions/Grove后续优化清单.md`
- [ ] 9.3 等待用户手动验收通过后执行 `openspec archive add-knowledge-agent-bounded-investigation`，再次运行 `openspec validate --all --strict` 并完成归档本地提交
- [ ] 9.4 停在 push/merge 前等待用户明确确认，不自行推送或合并
