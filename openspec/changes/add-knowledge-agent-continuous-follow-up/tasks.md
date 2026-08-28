## 1. 骨架搭建前置：硬化知识 Agent 基础

- [x] 1.1 修复最终引用校验：记录请求/有效/丢弃句柄数，事实性回答全部引用失效时改为 `insufficient` 且 Run 至少为 `partial`，部分失效时保留有效引用并标记 `partial`
- [x] 1.2 修复工具降级汇总：`ok`/正常 `empty` 不算 fallback，`partial`/`denied`/`unavailable`/`error` 均进入受影响阶段且 error 不得被标为正常
- [x] 1.3 将 `current_step` 更新与取消检查改为独立短会话读写，确保运行进度可轮询且 MySQL 长事务能看到其他请求刚提交的取消；终态条件阻止迟到步骤覆盖
- [x] 1.4 补齐全部/部分无效引用、正常空搜索、工具 error/partial、运行中步骤与跨会话取消回归测试，并运行 `cd backend && .venv/bin/python -m pytest tests/test_knowledge_agent_evidence.py tests/test_knowledge_agent_runner.py tests/test_knowledge_agent_worker.py`

## 2. 骨架搭建：上下文版本与 Run 契约

- [x] 2.1 新增不可变 `KnowledgeContextVersion` 与 `KnowledgeWorkingSetItem` 模型、状态/原因枚举、单活动版本约束、范围和标题短快照
- [x] 2.2 扩展 Conversation/Run，保存请求模式、实际决策、独立查询、主题、历史消息 ID、输入/输出工作集版本及上下文降级信息
- [x] 2.3 新增 Alembic 迁移并验证 SQLite/MySQL 8 的 `(conversation_id, active_slot)` 多终态 NULL 与单活动版本语义；既有对话保持无活动工作集
- [x] 2.4 扩展 Pydantic schemas：`context_mode` 默认 `auto`，Run/消息返回上下文决策和工作集摘要，回答状态支持无事实引用的 `clarification`
- [x] 2.5 增加模型、迁移、默认值、约束与序列化测试并运行 `cd backend && .venv/bin/python -m pytest tests/test_knowledge_agent_models.py tests/test_knowledge_agent_working_set.py`

## 3. 实现：上下文决策与有限历史

- [x] 3.1 新增结构化上下文决策 Agent，输出 `continue`/`new_topic`/`clarify`、独立查询、主题标签与澄清问题，并设置 prompt 版本、限长输入和有界重试
- [x] 3.2 实现有限历史选择：默认只取最近配置条数并截断内容，保存实际消息 ID；助手历史只进入决策阶段，不进入回答事实上下文
- [x] 3.3 实现应用层归一化和显式覆盖：`new_topic` 绕过分类并关闭旧工作集，`continue` 固定语义且只改写查询，无工作集时澄清
- [x] 3.4 实现安全降级：`auto` 分类失败按 `new_topic`，强制 `continue` 改写失败使用“主题 + 原问题”，所有路径记录 provider/model/fallback/error/耗时
- [x] 3.5 增加自动继续/新话题/澄清、显式覆盖、无工作集继续、历史限长、结构异常与模型降级测试，并运行 `cd backend && .venv/bin/python -m pytest tests/test_knowledge_agent_follow_up.py`

## 4. 实现：版本化工作集服务

- [x] 4.1 实现按用户、Workspace、对话和范围读取活动版本与复验工作集 Entry，删除、越权或移出范围的项只记录不可用
- [x] 4.2 实现输出版本构建：只接纳本轮最终有效引用 Entry；继续时合并旧有效项，新话题时替换，并按本轮引用/最近使用确定性截断到配置上限
- [x] 4.3 实现工作集生命周期：单活动版本、不可变父子版本、范围切换关闭、显式新话题立即关闭及历史版本审计
- [x] 4.4 将回答、Run 终态、活动槽释放和可选输出上下文切换放入同一事务；取消、失败、澄清不推进，继续追问无证据时保持旧版本，新话题知识不足时只允许建立零 Entry 的主题版本
- [x] 4.5 增加隔离、范围复验、版本并发、继续合并、新话题替换/空主题、上限截断、失败不推进和事务回滚测试，并运行 `cd backend && .venv/bin/python -m pytest tests/test_knowledge_agent_working_set.py`

## 5. 实现：连续追问固定执行图与可信工具

- [ ] 5.1 扩展 `RunToolContext`，只把固化输入工作集中复验有效的 Entry 加入服务端已发现集合，拒绝历史 Run Evidence 与模型猜测 ID
- [ ] 5.2 实现工作集种子与独立查询新召回的去重、统一重排与上下文截断；工作集不能阻止发现新 Entry 或无条件保留低相关项
- [ ] 5.3 扩展 Runner 为上下文决策分支：澄清直接回复；继续/新话题进入搜索、Entry、当前 Source Evidence、回答、引用校验和工作集更新
- [ ] 5.4 确保工作集 Entry 每轮重新读取 Attachment 并生成当前 Run Evidence，来源变化/删除时不复用历史 quote 或句柄
- [ ] 5.5 增加省略追问、对比扩展、新话题、澄清、工作集种子失效、新发现 Entry、历史 Evidence 拒绝与工具预算测试，并运行 `cd backend && .venv/bin/python -m pytest tests/test_knowledge_agent_tools.py tests/test_knowledge_agent_runner.py`

## 6. 实现：API 兼容与恢复

- [ ] 6.1 扩展消息提交 API 接收可选 `context_mode`，幂等重试始终返回首次模式/决策；旧客户端不传时保持 `auto`
- [ ] 6.2 扩展对话、消息和 Run 查询，返回活动主题摘要、上下文决策、独立查询、输入/输出版本与澄清状态，同时保持其他用户/Workspace 一律 404
- [ ] 6.3 扩展范围切换事务关闭活动工作集；活动 Run 期间仍返回 409 且不改变范围或版本
- [ ] 6.4 确保 Worker 崩溃恢复继续使用 Run 固化输入版本，重复执行不产生多个活动工作集或重复助手回答
- [ ] 6.5 增加 API 级默认/显式模式、幂等、轮询进度、澄清、版本恢复、范围切换和跨 Workspace 隔离测试，并运行 `cd backend && .venv/bin/python -m pytest tests/test_knowledge_agent_api.py tests/test_knowledge_agent_worker.py`

## 7. 验证与收尾

- [ ] 7.1 运行后端完整测试与静态检查：`cd backend && .venv/bin/python -m pytest && .venv/bin/ruff check app tests`
- [ ] 7.2 在 SQLite 用真实 API 走查首问、自动追问、强制继续、强制新话题、澄清、范围切换、引用重新核验、幂等和取消，并记录 curl 请求、状态码、决策与工作集版本
- [ ] 7.3 使用可用 MySQL 8 环境验证迁移、单活动工作集约束、运行中步骤可见、跨事务取消和崩溃恢复；记录环境与结果
- [ ] 7.4 运行 `openspec validate --all --strict`，核对实现与 proposal、design、六份 delta specs 及权威产品专题一致
- [ ] 7.5 向用户逐条说明遗留问题与影响，获同意后再登记后续优化；用户手动验收通过后执行 `openspec archive add-knowledge-agent-continuous-follow-up` 并同步主规格
- [ ] 7.6 归档后完成本地提交并停在 push/merge 前，等待用户明确确认
