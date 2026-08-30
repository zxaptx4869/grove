## 1. 实施前基线与契约核对

- [ ] 1.1 重新阅读本 change 的 proposal/design/specs、`AGENTS.md`、`docs/产品蓝图.md` 路由到的「Agent架构与AI边界」「目录与知识空间」「技术与端侧边界」，并核对 `grove-ui-conventions` 与移动原型的整理路径；把实施中发现的规格歧义先更新工件，不静默扩范围。
- [ ] 1.2 盘点 `KnowledgeAgentRun`/Message Page/Worker、旧 `save_answer_as_candidate`、Candidate 创建/路由/关系服务及移动 AnswerCard/controller 的当前契约，确认普通 answer Run、旧 Reader 和既有移动只读流程的兼容基线。
- [ ] 1.3 运行 `cd backend && .venv/bin/python -m pytest tests/test_reader.py tests/test_knowledge_agent_conversations.py tests/test_knowledge_agent_runs.py -W error` 与 `cd mobile && npm test -- --runInBand && npm run lint && npm run typecheck`，记录实施前结果。

## 2. Candidate Draft 数据模型与迁移

- [x] 2.1 为 `KnowledgeAgentRun` 增加向后兼容的 `run_kind` 与可选 `source_run_id`，为既有数据默认/回填 `answer`；增加 source Run 自引用、索引和合法值约束所需应用校验。
- [x] 2.2 新增 `KnowledgeCandidateDraft` 模型、状态常量、owner/Workspace/Conversation/operation Run/source Run/target project/草稿字段/Evidence JSON/生成元数据/confirmed Candidate 关联及并发幂等约束。
- [x] 2.3 编写并审查 Alembic 迁移，确认 SQLite upgrade 与生产 MySQL 8 的外键、唯一约束、默认值和回滚顺序兼容；运行 `cd backend && .venv/bin/alembic upgrade head`。
- [x] 2.4 为模型约束、既有 Run 回填、Draft 状态/唯一关系与迁移后 schema 增加测试，运行相应 pytest 与 `cd backend && .venv/bin/ruff check app tests`，通过后完成一次本地提交。

## 3. Run-backed Evidence 与共享 Candidate 创建服务

- [x] 3.1 从旧 Reader 保存逻辑抽取只接受已校验参数的虚拟 Source/Attachment/Extraction/pending Candidate 创建服务，保留原问题、原回答、编辑草稿、source Run 与目标项目溯源元数据，不通过内部 HTTP 复用。
- [x] 3.2 实现 source Run、最终 citations、目标项目和当前 Entry/Source/Attachment/quote/指纹的服务端解析与重验；Workspace 多项目返回可选项目，项目范围固定目标，客户端对象 ID/quote 不进入可信输入。
- [x] 3.3 让旧 `/reader/save-candidate` 完成原有校验后调用共享服务，保持响应、同步路由/关系建议和既有测试兼容；补充旧 Reader 与新服务事务失败不留半成品的测试。
- [x] 3.4 实现 Draft 确认事务与稳定 `client_operation_id` 幂等：并发最多创建一个 Source/Candidate，confirmed 重放返回同一对象，Evidence 失效返回 409，任何路径不创建/修改 Entry。
- [x] 3.5 覆盖跨用户/Workspace/Conversation/project、历史快照但当前来源失效、未知句柄、跨项目 Evidence、重复确认、并发确认及路由/关系受影响场景；运行 `cd backend && .venv/bin/python -m pytest tests/test_reader.py tests/test_knowledge_agent_candidate_drafts.py -W error`，通过后本地提交。

## 4. 草稿生成 Agent 与受控 operation Run

- [ ] 4.1 定义 PydanticAI 候选草稿输入/输出、独立 prompt version 与依赖：只暴露原问题、原回答编辑上下文、目标项目、受限 Evidence 句柄/原文，输出 title/content/main_type/info_nature/selected handles，不允许项目或数据库对象写入参数。
- [ ] 4.2 实现显式 `draft_candidate` 提交流程：同事务创建可见用户消息、助手占位、`run_kind=draft_candidate` waiting Run 与 generating Draft，复用 Conversation 活动槽与 `client_message_id` 幂等；普通消息始终创建 answer Run。
- [ ] 4.3 扩展 Worker 领取与执行分发，operation Run 只执行 Evidence 复验、草稿生成、句柄白名单校验和终态提交，不执行上下文决策、answer mode、搜索、调查或工作集推进。
- [ ] 4.4 实现 operation Run 的取消、租约恢复、重试上限与原子终态；恢复复用同一 Run/Draft，失败/取消不创建 Source/Candidate，也不推进工作集。
- [ ] 4.5 记录草稿模型 provider/model/fallback/error/usage/duration 与受影响阶段；实现明确的确定性 seed 降级或稳定失败语义，禁止把无模型或非法 schema 标为正常成功。
- [ ] 4.6 为成功、partial 只用有效证据、无引用拒绝、非法句柄、模型失败/降级、取消、恢复、活动 Run 409、重复提交和工作集不变补充测试；运行 `cd backend && .venv/bin/python -m pytest tests/test_knowledge_agent_candidate_drafts.py tests/test_knowledge_agent_runner.py -W error && .venv/bin/ruff check app tests`，通过后本地提交。

## 5. Conversation / Draft API 与历史归并

- [ ] 5.1 扩展后端 schemas：动作资格/可选目标项目、Run kind/source Run、Draft、编辑请求、确认请求/回执和明确错误；字段命名与移动端 snake_case 适配保持一致。
- [ ] 5.2 新增显式草稿动作提交、Draft 读取/PATCH/取消/确认端点，所有端点同时校验 owner + Workspace + Conversation；确认请求不接收自由引用字段。
- [ ] 5.3 扩展 Message Page 规范化返回关联且去重的 `candidate_drafts`，对话列表/消息查询不得产生逐消息或逐 Draft N+1；历史范围切换后保留 Draft 目标项目快照。
- [ ] 5.4 补充 API 201/200 幂等、400/404/409、分页历史、查询数量、普通 answer 兼容、Bearer 移动鉴权和旧客户端缺省字段测试；先以 curl 验证新端点非 404，再运行相关 API pytest。
- [ ] 5.5 运行 `cd backend && .venv/bin/python -m pytest -W error && .venv/bin/ruff check app tests`，确认全量通过后完成一次后端阶段本地提交。

## 6. 移动端领域层与恢复控制器

- [ ] 6.1 扩展 TypeScript 类型、snake_case 适配、API、query keys 与错误分类，覆盖 Run kind、source Run、目标项目、Draft 状态、编辑、取消、确认和 Candidate 回执；不从回答正文解析写动作。
- [ ] 6.2 在 answer adapter 中按结构化 status/citations/可选项目计算动作资格；completed/partial 有引用可整理，其余状态不暴露入口，partial 明确只整理有依据部分。
- [ ] 6.3 扩展 Conversation controller：项目范围直接提交，Workspace 多项目先选目标；动作使用稳定 client_message_id，确认使用稳定 client_operation_id，未知结果重试复用原键并以服务端 Draft/Candidate 为权威。
- [ ] 6.4 将 Draft 归并到 operation Run/message，生成中只在前台轮询，终态 refetch；后台、重启、历史分页、切换对话和范围切换后恢复 generating/draft/failed/cancelled/confirmed，不复制本地权威状态。
- [ ] 6.5 为动作资格、目标项目、序列化、重复点击、活动 Run 409、未知确认结果、消息/Draft 去重、前后台与历史恢复补充 adapter/API/controller 测试；运行 `cd mobile && npm test -- --runInBand && npm run lint && npm run typecheck`，通过后本地提交。

## 7. 原生候选草稿界面与原型对齐

- [ ] 7.1 按 `grove-mobile-agent-prototype.html` 提取本次路径的 Agent 标签、卡片顺序、Badge、字段层级、Sheet、按钮、间距、圆角、色彩与回执视觉基线，并把实现后的实际有意偏离与 design 对齐；正式代码只复用 React Native/Grove 组件和主题。
- [ ] 7.2 在 AnswerCard 引用/范围之后增加「整理成知识」结构化动作；项目范围直接发起，Workspace 多项目使用只列项目的目标 Sheet，不展示目录节点或隐式收窄范围。
- [ ] 7.3 实现生成过程、失败/降级重试和 Candidate Draft 卡；草稿卡显示 `AI 草稿 · 未创建候选`、目标项目、标题、正文、类型、来源摘要和「编辑并检查」，与即时回答/正式知识语义分离。
- [ ] 7.4 实现可滚动原生编辑 Sheet 与确认 Sheet：长标题/正文、多行键盘、类型选择、取消、保存编辑、创建中 disabled 和“创建待确认知识”后果说明均可操作。
- [ ] 7.5 实现 confirmed 回执，显示目标项目、Candidate 待确认、来源保留、标识/时间和“尚未写入正式知识”；目录/关系 pending 或受影响时显示真实状态，不伪造移动确认台跳转、正式归档或撤销。
- [ ] 7.6 为 eligible/ineligible、单/多项目、生成、长草稿、编辑、取消、确认中、超时重试、成功回执、路由受影响、历史恢复和错误状态补充组件测试；运行移动 test/lint/typecheck 后本地提交。

## 8. 视觉、键盘与可访问性验收

- [ ] 8.1 在 390×844 主视口逐项对照原型走查回答动作、项目 Sheet、用户操作消息、过程卡、草稿卡、编辑 Sheet、确认 Sheet、回执与错误恢复；核对元素顺序、水平对齐、视觉重量、文字层级、间距、边框、圆角和按钮样式。
- [ ] 8.2 在 360×800 与 412×915 验证短/长草稿、动态字体、文本缩放、长项目名、多个来源和错误文案，无横向溢出、截断或固定控件跳动。
- [ ] 8.3 在可用的 iOS/Android 真机或模拟器验证系统键盘开闭、多行增长、滚动、焦点归还、安全区、底栏隐藏/恢复和返回行为；若工具链不可用，明确记录未验证项，不以 Web 伪键盘代替原生验收。
- [ ] 8.4 校验 44×44 触控目标、读屏 label/state/order、非颜色状态、reduce-motion 和 Sheet 长内容滚动；将代表性三视口截图与走查记录放入本 change 的 `validation/`，不提交构建包、密钥或 `.env`。

## 9. 纵向走查与全量验证

- [ ] 9.1 用真实 Bearer Session 和真实服务端 Run 走查：项目回答整理、Workspace 单项目预填、多项目选择、partial 只整理有效部分、无引用拒绝、编辑、取消、确认、未知结果重试、Evidence 失效 409、历史恢复与跨 Workspace 404。
- [ ] 9.2 核对确认后只新增虚拟 Source/Attachment/Extraction/pending Candidate，未新增/修改 Entry；在桌面既有确认台确认 Candidate、目录建议、关系建议和来源均可正常查看，旧 Reader 保存仍可用。
- [ ] 9.3 运行 `cd backend && .venv/bin/python -m pytest -W error && .venv/bin/ruff check app tests`，运行 `cd mobile && npm test -- --runInBand && npm run lint && npm run typecheck && npx expo export --platform ios && npx expo export --platform android`，再运行 `git diff --check`。
- [ ] 9.4 运行 `openspec validate add-knowledge-agent-candidate-drafting --strict` 与 `openspec validate --all --strict`；逐项核对 specs、原型偏离、可观测性、Workspace 隔离、Candidate/Entry 文案和任务勾选。
- [ ] 9.5 更新 `validation/validation.md` 的真实命令、测试数量、curl/设备结果与未验证项；完成最终本地提交并停留在特性分支等待用户体验，不 archive、push 或 merge。
