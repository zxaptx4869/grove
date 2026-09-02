## 1. 数据与协议骨架

- [x] 1.1 在 Knowledge Agent 领域常量、SQLAlchemy Run 模型和设置中增加 `basis_mode`、规划策略、`answer_basis`、`basis_route` 步骤/用途及开放讨论特性开关，保持旧记录字段可空。验收：`cd backend && .venv/bin/ruff check app/models/knowledge_agent.py app/config.py`
- [x] 1.2 新增同时兼容 SQLite 与 MySQL 8 的 Alembic 迁移，为 `knowledge_agent_runs` 增加请求依据模式、规划策略和实际依据 JSON 字段，不回填猜测旧回答。验收：`cd backend && .venv/bin/alembic upgrade head && .venv/bin/alembic current`
- [x] 1.3 扩展 Pydantic 请求/响应与 API 适配，要求新客户端显式提交 `basis_mode=auto`、旧客户端缺少字段时兼容为 `knowledge_only`，并支持同 `client_message_id` 重试复用首次模式及 Run/消息页可选 basis 字段。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_api.py tests/test_knowledge_agent_conversations.py`

## 2. 依据规划与用户陈述边界

- [x] 2.1 实现结构化 basis planner 与版本化提示，输出受限策略、是否需要 Grove/外部材料和候选用户消息句柄；显式 `knowledge_only` 由应用直接执行，规划失败显式回退 Grove-only。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_models.py -k basis`
- [x] 2.2 实现当前话题有界用户陈述加载与服务端句柄校验，只允许同 Conversation、同范围、当前上下文链中的用户消息，并在 new_topic、范围切换和未完成澄清时切断继承。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_follow_up.py -k statement`
- [x] 2.3 将 basis planner 调用接入现有模型调用审计与 Run fallback 汇总，覆盖成功、非法结构、未配置模型、显式跳过规划和未知消息 ID。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_runner.py -k basis`

## 3. 依据感知回答执行

- [x] 3.1 调整 answer Run 编排顺序，在 `actual_result_mode=answer` 时先解析 basis；实现 model-first 跳过 Grove、需要 Grove 时复用现有 quick 图、entries 结果跳过 basis 规划。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_runner.py tests/test_knowledge_agent_result_protocol.py`
- [x] 3.2 扩展结构化回答草稿与提示，使允许模型知识的回答可以包含无 Citation 要点，同时继续由服务端剔除未知 Evidence、派生 Citation、处理冲突并禁止声称联网。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_evidence.py tests/test_knowledge_agent_models.py`
- [x] 3.3 实现服务端 `AnswerBasis v1` 装配与状态计算：从最终 Citation、已校验用户消息和实际执行权限派生依据；将“无 Citation”与 insufficient 解耦，并原子提交回答、basis、Run 终态和可选工作集。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_result_protocol.py tests/test_knowledge_agent_working_set.py`
- [x] 3.4 调整空搜索、Entry/Evidence 不可用和回答模型失败路径：允许的开放回答按实际完成度返回 completed/partial/insufficient，`knowledge_only` 保持严格不足，任何降级均可见。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_runner.py -k 'empty or unavailable or fallback or knowledge_only'`
- [x] 3.5 将 basis 接入有界调查：显式 investigate 必须真实创建 Investigation；自动 model-first 不伪造调查；无 Grove 结果时按用户限制决定一般回答或不足，并保留真实停止原因。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_investigation_runner.py tests/test_knowledge_agent_investigation_recovery.py`
- [x] 3.6 覆盖取消、租约恢复、重复执行与终态事务一致性，确保恢复复用已提交的 basis 规划、取消不提交迟到回答、实际 basis 不漂移。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_worker.py tests/test_knowledge_agent_investigation_recovery.py`

## 4. 旧 Candidate Draft 兼容

- [x] 4.1 在服务端增加旧 `draft_candidate` 资格校验：新 Run 仅允许可证明的纯 Grove 依据回答，模型优先、混合、用户陈述或外部缺口回答即使有 Citation 也拒绝；旧 Run 沿用最终 Evidence 复验。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_candidate_drafts.py tests/test_knowledge_agent_draft_api.py`
- [x] 4.2 验证旧 pending Candidate、历史 Draft、旧 Reader 共享创建服务和单 Entry Revision 不受 basis 字段影响，不创建或覆盖正式 Entry。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_candidate_drafts.py tests/test_knowledge_agent_entry_revision.py`

## 5. 原生端协议与一次性模式

- [x] 5.1 扩展原生领域类型、snake_case 适配与 API 请求，兼容旧服务端缺少 basis 字段，并在提交结果未知时保留同一 basis mode 与 `client_message_id`。验收：`cd mobile && npm test -- --runInBand src/knowledge-agent/api.test.ts src/knowledge-agent/state/submission.test.ts`
- [x] 5.2 扩展一次性 ModeSelection 与 Mode Sheet，增加“依据：自动选择 / 仅使用我的知识库”，非默认选择显示可移除 Chip，成功提交后重置。验收：`cd mobile && npm test -- --runInBand src/knowledge-agent/state/modes.test.ts src/knowledge-agent/hooks/useConversationController.test.tsx`

## 6. 原生回答依据展示

- [x] 6.1 新增 basis 展示适配器，完全根据服务端结构化字段生成紧凑概览，不解析正文或工具过程；旧回答缺少 basis 时维持现有展示。验收：`cd mobile && npm test -- --runInBand src/knowledge-agent/adapters/answer.test.ts`
- [x] 6.2 在 AnswerCard 中区分“AI 即时回答”“基于你的知识”和混合依据，支持无 Citation 的 completed 回答，不把回答、用户陈述或模型知识显示为 Candidate/Entry。验收：`cd mobile && npm test -- --runInBand src/knowledge-agent/components/components.test.tsx -t '依据|无引用|开放回答'`
- [x] 6.3 实现可滚动依据详情：Grove 项复用 Citation Sheet，用户陈述显示服务端摘要并可定位消息，模型知识与外部材料只显示性质和边界；关闭后恢复对话位置与焦点。验收：`cd mobile && npm test -- --runInBand src/knowledge-agent/components/components.test.tsx -t '依据详情|用户陈述|外部材料'`
- [x] 6.4 按服务端资格控制固定“整理成知识”入口，确保混合/模型回答隐藏、旧历史回答继续可恢复，服务端拒绝时显示就地错误。验收：`cd mobile && npm test -- --runInBand src/knowledge-agent/adapters/answer.test.ts src/knowledge-agent/hooks/useConversationController.test.tsx`

## 7. 代表性评估与自动验证

- [x] 7.1 建立开放讨论评估夹具，覆盖模型优先、知识优先、混合依据、仅我的知识、当前陈述冲突、时效/高风险、外部材料缺口和同义表达。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_open_discussion.py`
- [x] 7.2 增加安全硬门禁测试，保证伪造 Citation、突破 knowledge_only、跨 Workspace/项目读取、静默降级和伪装实时外部结果均为零。验收：`cd backend && .venv/bin/pytest -q tests/test_knowledge_agent_open_discussion.py -k guardrail`
- [x] 7.3 完成后端全量测试与静态检查，并在迁移代码完成后再次应用最新迁移。验收：`cd backend && .venv/bin/alembic upgrade head && .venv/bin/pytest -q && .venv/bin/ruff check app tests alembic`
- [x] 7.4 完成原生端全量单测、类型检查与 lint。验收：`cd mobile && npm test -- --runInBand && npm run typecheck && npm run lint`

## 8. 手动走查与收尾

- [x] 8.1 启动后端后用 curl 验证 Conversation、消息提交、Run 查询和历史接口存在且返回预期 401/200 而非 404，并记录 model-first、knowledge-only、hybrid、investigate 和 fallback 响应。验收：将命令与响应摘要写入 `docs/验收记录/add-knowledge-agent-open-discussion-curl.md`
- [x] 8.2 在 360×800、390×844、412×915 三个原生视口走查空知识开放讨论、混合追问、仅我的知识、依据详情、深度查找、失败重试、历史恢复、键盘和读屏标签。验收：在验收记录中列出各视口结果、截图路径、控制台结果和剩余差异
- [x] 8.3 更新 Knowledge Agent 产品形态与迭代记录中的“已完成能力/下一步缺口”，只在实现与验收真实完成后移动状态，不提前覆盖主规格。验收：`openspec validate --all --strict`
- [ ] 8.4 检查本 change 是否存在遗留问题或后续优化项；逐条向用户说明背景、原因与影响，用户同意后再登记到 `docs/discussions/Grove后续优化清单.md`。验收：`git status --short`
