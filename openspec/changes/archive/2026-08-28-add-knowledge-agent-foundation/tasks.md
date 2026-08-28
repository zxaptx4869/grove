## 1. 骨架搭建：数据模型与迁移

- [x] 1.1 新增知识对话、消息、Agent Run、工具调用、模型调用与 Run Evidence 的 SQLAlchemy 模型和枚举，落实用户/Workspace 归属、范围快照、外键、游标排序字段与内容指纹
- [x] 1.2 为 `(conversation_id, client_message_id)` 幂等键和 `(conversation_id, active_slot)` 单活动 Run 约束新增 Alembic 迁移，并确认终态 `active_slot=NULL` 同时兼容 SQLite 与 MySQL 8
- [x] 1.3 新增对话、范围、消息、Run、阶段记录、Evidence 与分页响应的 Pydantic schemas，确保 API 不返回原始 prompt 或整份 Attachment
- [x] 1.4 增加模型与迁移测试并运行 `cd backend && .venv/bin/python -m pytest tests/test_knowledge_agent_models.py`

## 2. 骨架搭建：对话与 Run 应用服务

- [x] 2.1 实现按当前用户与 Workspace 创建、列出、读取知识对话以及游标分页读取消息的仓储和服务
- [x] 2.2 实现 Workspace/项目范围校验与 `scope_change` 系统消息，活动 Run 期间切换范围返回冲突，历史消息和 Run 保留范围快照
- [x] 2.3 实现用户消息幂等提交，在单事务中创建用户消息、助手占位消息与 `waiting` Run，并以数据库约束保证同会话串行
- [x] 2.4 增加对话所有权、跨 Workspace 404、越权项目、范围切换、分页、幂等与并发冲突测试，并运行 `cd backend && .venv/bin/python -m pytest tests/test_knowledge_agent_conversations.py`

## 3. 实现：可信只读工具与 Evidence

- [x] 3.1 抽取 Run 工具上下文与已发现对象集合，使用户、Workspace、项目范围只能由服务端注入，模型猜测的 UUID 无法越过搜索/用户显式引用边界
- [x] 3.2 实现 `search_confirmed_knowledge`，复用混合召回且只返回范围内正式 Entry；Workspace 结果携带项目归属，目录仅作为定位信息
- [x] 3.3 实现批量 `read_entries`，在读取时复验范围与已发现集合，并返回完整正式内容、项目、目录和真实来源关系
- [x] 3.4 实现 `read_source_evidence`，复用证据归一化在 Attachment `text_content` / `ocr_text` 中取得精确原文，并保存可引用 Evidence 与内容指纹
- [x] 3.5 实现 Evidence 句柄解析和最终引用校验，拒绝跨 Run 句柄、模型自由 quote、无真实关联 Source 与无法核验片段
- [x] 3.6 增加 Workspace/项目搜索、候选排除、已发现集合、跨范围读取、OCR 归一化、无效关联和伪造引用测试，并运行 `cd backend && .venv/bin/python -m pytest tests/test_knowledge_agent_tools.py tests/test_knowledge_agent_evidence.py`

## 4. 实现：固定执行图、可观测性与 Worker

- [x] 4.1 调整混合召回与 Reader 回答组织器，使 embedding、重排和回答分别返回 provider/model/fallback/error/耗时元数据，同时保持旧 Reader 调用方兼容
- [x] 4.2 实现有服务端预算的固定执行图：搜索、读取 Entry、读取 Evidence、组织回答、校验引用；每个新问题独立检索且最多使用 15 条 Entry
- [x] 4.3 持久化每次工具调用与模型调用，聚合 Run 降级摘要；回答模型不可用时返回可识别的 `partial` 或 `failed`，不得静默伪装成功
- [x] 4.4 实现 Worker 原子领取、步骤状态、租约、一次崩溃恢复、重试上限和终态事务提交，防止多个 Worker 生成重复答案
- [x] 4.5 实现 `waiting` / `processing` Run 取消和步骤边界检查，取消后的模型结果不写入正常助手消息
- [x] 4.6 增加正常回答、知识不足、冲突、各阶段降级、工具预算、并发领取、崩溃恢复、取消和原子提交测试，并运行 `cd backend && .venv/bin/python -m pytest tests/test_knowledge_agent_runner.py tests/test_knowledge_agent_worker.py`

## 5. 实现：知识 Agent API 与兼容边界

- [x] 5.1 新增 `/api/knowledge-agent` 对话创建/列表/详情、消息分页、范围切换、消息提交、Run 查询和取消路由，全部复用当前 Session/Bearer 鉴权
- [x] 5.2 保留旧项目 Reader 与 `answer-to-candidate` 接口行为，标记兼容边界并确认新 API 不提供知识写入或保存建议字段
- [x] 5.3 增加 API 级认证、404 隔离、409 单会话冲突、幂等重试、轮询恢复、取消、结构化回答和 Evidence 引用测试，并运行 `cd backend && .venv/bin/python -m pytest tests/test_knowledge_agent_api.py tests/test_reader.py`
- [x] 5.4 启动开发后端并用 `curl` 验证新端点返回预期 401/200/202/404/409 而非 404 路由缺失，记录可复现的命令与结果

## 6. 验证与收尾

- [x] 6.1 运行后端完整测试与静态检查：`bash scripts/backend-test.sh && cd backend && .venv/bin/ruff check app tests`
- [x] 6.2 在 SQLite 完成 Workspace 问答、项目问答、跨 Workspace 隔离、真实原文引用、幂等、取消、重启恢复和降级手动走查；使用可用 MySQL 8 环境验证迁移与单活动 Run 约束
- [x] 6.3 运行 `openspec validate --all --strict`，并核对实现与 proposal、design、四份 delta specs 及权威产品专题一致
- [x] 6.4 向用户逐条说明遗留问题与影响，获同意后再登记后续优化；用户验收通过后执行 `openspec archive add-knowledge-agent-foundation` 并同步主规格
- [x] 6.5 归档后完成本地提交并停在 push/merge 前，等待用户明确确认
