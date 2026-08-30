## 1. 开工基线与视觉准备

- [x] 1.1 阅读 `AGENTS.md`、本 change 全部工件、相关主规格、产品专题和移动原型对应片段，使用 `openspec-apply-change` 与 `grove-ui-conventions`，确认本 change 只做单 Entry 修订与安全撤销
- [x] 1.2 开发前确认当前分支已吸收用户单独处理并合入 `main` 的三个前置修复；若尚未合入则停止并汇报，不在本 change 重复实现或绕开
- [x] 1.3 记录当前后端/移动测试数量、ruff、lint、typecheck 与 `openspec validate --all --strict` 基线，确认失败不是由本 change 引入后再继续
- [x] 1.4 提取移动原型中修订指令、草稿、完整差异、确认、回执和撤销的视觉基线，记录元素顺序、间距、徽标、按钮、长内容、键盘、安全区与本 change 有意偏离
- [x] 1.5 检查现有 Entry 版本、AI 修订、Candidate 应用、Evidence、项目上下文刷新和 embedding 标记服务，列出可复用函数与需抽取的边界，不通过内部 HTTP 复用
- [x] 1.6 完成基线与设计核对本地提交，提交信息使用 `docs: 核对知识 Agent 单条修订基线`

## 2. 数据模型与迁移骨架

- [x] 2.1 新增 `KnowledgeEntryRevisionDraft` 模型、状态常量、owner/Workspace/Conversation/source Run/target Entry/基线/Evidence/候选字段/执行关联与时间字段
- [x] 2.2 新增 `KnowledgeEntryRevisionExecution` 模型，保存幂等键、before/after snapshot 与 fingerprint、前后版本、本操作新增 Evidence ids、applied/undone 状态和时间
- [x] 2.3 扩展 `KnowledgeAgentRun` 的 `entry_revision` 类型与 target_entry_id 关联，保持既有 answer/draft_candidate 数据默认和迁移兼容
- [x] 2.4 增加 SQLite/MySQL 兼容的 Alembic 迁移、唯一约束、外键和高频查询索引；upgrade/downgrade 不修改既有 Entry、Run 或 Candidate 数据
- [x] 2.5 补模型/迁移测试：合法状态、唯一 operation Run/Execution、会话内幂等键、Run 类型兼容、FK 行为、fresh SQLite 迁移和 downgrade→upgrade
- [x] 2.6 运行模型/迁移定向 pytest、ruff 与 `alembic upgrade head`，完成本地提交 `feat: 建立知识 Agent 单条修订数据骨架`

## 3. 显式动作、目标与 Evidence 校验

- [x] 3.1 扩展 schemas：`revise_entry` 动作请求、Revision Draft/差异/Execution/确认/撤销输入输出和消息页规范化集合，所有用户文本与枚举设置长度/类型约束
- [x] 3.2 实现 source Run 与 target Entry 校验：同 owner/Workspace/Conversation、回答 completed/partial、Entry 位于最终有效 citations、目标项目由 Entry 决定、越权统一 404
- [x] 3.3 只从最终 answer points/citations/conflicts 收集允许 Evidence，并逐条复验 Run、项目、Entry/Source/Attachment、quote 与内容指纹；不得加载回答未采用的整轮 Evidence
- [x] 3.4 实现 Entry 基线 snapshot、最新版本解析和稳定 fingerprint；覆盖必填/可空字段、node id、JSON 规范化与旧 Entry 无版本的兼容处理
- [x] 3.5 实现幂等 submit：可见用户消息、entry_revision Run、generating Draft 和活动槽在同一事务内创建；重复 client_message_id 返回同一对象
- [x] 3.6 补目标未引用、跨项目/Workspace/用户、历史 Evidence 失效、普通 answer 消息不触发、空指令、活动 Run 冲突和幂等测试
- [x] 3.7 运行本组后端定向测试与 ruff，完成本地提交（阶段 3-5 共用单服务模块，合并为一次提交）

## 4. 修订草稿 Agent 与可恢复 Run

- [x] 4.1 新增 Knowledge Agent 专用单 Entry revision Agent 输出：字段全集、change_summary、reason、selected Evidence handles；提示词禁止模型常识、联网、对象 ID 和执行声称
- [x] 4.2 抽取可复用的 Entry 上下文/字段归一化能力，但保持桌面 Revision Agent 的外部知识语义与无状态接口不变
- [x] 4.3 实现 `execute_entry_revision_run`：租约与状态校验、目标/Evidence 复验、模型调用、句柄白名单、无差异失败、Draft/Run/助手消息原子终态和活动槽释放
- [x] 4.4 将 entry_revision 分支接入 Worker 领取、恢复、重试与取消；不得执行 answer 搜索/调查或创建输出工作集
- [x] 4.5 记录 revision draft 模型 purpose、provider/model/fallback/error/duration；未配置模型、异常或非法输出不得生成伪草稿
- [x] 4.6 补成功、未知句柄、回答未采用 Evidence 排除、跨项目 Evidence、模型失败、无实际差异、崩溃恢复、重试耗尽、取消边界和工作集不推进测试
- [x] 4.7 运行 Agent/Worker 定向测试与 ruff，完成本地提交（并入阶段 3-5 合并提交）

## 5. Draft 编辑、服务端差异与消息恢复

- [x] 5.1 实现按 owner + Workspace 读取 Revision Draft，越权统一 404；Message Page 批量归并当前页 Draft/Execution，避免 N+1 和敏感基线泄漏
- [x] 5.2 实现 draft 状态的候选字段与 change_summary 编辑、字段清洗和服务端 changed fields 计算；拒绝 target/source/base/Evidence 受保护字段
- [x] 5.3 实现取消：generating 时取消关联 Run，draft 时只进入 cancelled；applied/undone/failed 状态不可非法回退
- [x] 5.4 新增 submit、edit、cancel、get 等 Knowledge Agent API 路由；confirm/undo 路由随 6/7 阶段补充；新增端点以 API 测试验证 401/200/4xx 而非 404
- [x] 5.5 补历史分页、重启恢复、长字段、字段清空、diff 稳定顺序、非法状态、跨用户/Workspace 和既有 answer/Candidate Draft 响应兼容测试
- [x] 5.6 运行 API/Conversation 定向测试与 ruff，完成本地提交（并入阶段 3-5 合并提交）

## 6. 原子应用、版本、Evidence 与执行审计

- [x] 6.1 抽取/扩展 Entry 应用服务，使字段更新、版本追加、Evidence 去重、Project Context 刷新和 embedding 标记可由现有桌面路径与 Knowledge Agent 在各自校验后复用
- [x] 6.2 确定并实现 SQLite/MySQL 兼容的 Evidence 等价去重策略；只记录本次事务真实新增的 `EntrySourceEvidence` id，不改变既有桌面行为
- [x] 6.3 实现 Draft 条件锁定与稳定 `client_operation_id`：重新校验 target/source/Evidence、base fingerprint 和最新版本，无变化或过期基线返回 409 并恢复可编辑状态
- [x] 6.4 在单事务中应用字段、补充 Evidence、追加明确 Knowledge Agent 修订版本、创建 Execution、更新 Draft；任一步失败整体回滚
- [x] 6.5 记录 confirm 工具调用的真实状态、版本、Evidence 增量、错误和耗时；响应成功不得掩盖工具失败
- [x] 6.6 补首次应用、幂等重放、并发确认、基线过期、Evidence 失效、无差异、重复 Evidence、不重复版本、事务失败回滚及桌面编辑/AI 修订/Candidate 修订兼容测试
- [x] 6.7 运行 Entry/确认定向测试、ruff 和必要的 SQLite/MySQL 迁移/事务测试，完成本地提交 `feat: 原子应用知识 Agent 单条修订`

## 7. 并发安全撤销

- [ ] 7.1 实现 Execution/Draft 条件状态转换和幂等 undo key，校验 after fingerprint 与最新 applied version；后续修改时稳定返回 409
- [ ] 7.2 在单事务中恢复 before snapshot、只删除本操作新增且仍属目标 Entry 的 Evidence、追加 restored 版本、刷新 Project Context/embedding 并标记 undone
- [ ] 7.3 撤销不得删除既有/等价复用/其他操作新增 Evidence；不得依赖已经可能被滚动清理的旧 EntryVersion 作为唯一 before 数据
- [ ] 7.4 记录 undo 工具调用、结果与错误；失败保持 applied，已 undone 重试返回同一结果且不追加第二个恢复版本
- [ ] 7.5 补成功撤销、重复撤销、响应未知重试、人工编辑/移动/再次修订/版本恢复阻止撤销、Evidence 精确删除、事务失败回滚和越权测试
- [ ] 7.6 运行撤销定向测试与 ruff，完成本地提交 `feat: 支持知识 Agent 修订安全撤销`

## 8. 原生领域层与控制器

- [ ] 8.1 扩展 mobile Knowledge Agent 类型、API 客户端、query keys 和 adapters，兼容 `entry_revision_drafts` 缺失的旧响应
- [ ] 8.2 实现从 citation target 提交非空指令、乐观用户消息/服务端归并、operation Run 轮询/取消、Draft 编辑、确认与撤销的稳定 idempotency key
- [ ] 8.3 实现 applied/undone 后 Conversation、Entry、版本、引用与项目知识查询失效；App 后台停止轮询、回前台/重启按服务端恢复
- [ ] 8.4 对 401、404、409、422、网络未知、模型失败、Evidence 失效、版本冲突和撤销冲突提供领域错误映射，不用本地状态伪装终态
- [ ] 8.5 补 adapter、API、controller、消息去重、重复点击、恢复、取消、确认/撤销幂等、query invalidation 和错误映射测试
- [ ] 8.6 运行移动端定向 Jest、lint 与 typecheck，完成本地提交 `feat: 接入原生端单条知识修订协议`

## 9. 原生修订界面与原型对齐

- [ ] 9.1 在当前有效 Citation Sheet 中增加 target 明确的“修订这条知识”，失效快照/非 Entry/不可写状态隐藏或禁用；保留引用阅读主流程
- [ ] 9.2 实现可滚动 Revision Instruction Sheet：Entry 标题、项目/目录、当前摘要、非空指令、提交/关闭、键盘与焦点恢复
- [ ] 9.3 实现 Revision Draft Card 与编辑 Sheet：AI 建议语义、目标、变更字段、来源、长字段编辑、生成/失败/取消状态
- [ ] 9.4 实现单 Entry 全屏差异审阅：按字段展示原值/候选值、未变字段收敛、来源可达、返回状态与长内容滚动
- [ ] 9.5 实现确认 Sheet、执行中状态与 applied 回执：更新 1 条正式知识、版本、来源增量、查看 Entry/差异和撤销边界
- [ ] 9.6 实现撤销二次确认、undoing、undone、后续版本冲突和失败重试；不得出现多 Entry 合并/冲突保留/重复标记文案
- [ ] 9.7 补组件测试：Candidate 与 Revision 文案区分、44×44 触控、accessibility label、Sheet/Overlay 关闭、长内容滚动、键盘布局和各错误终态
- [ ] 9.8 运行移动端全量 Jest（不得 `--forceExit`）、lint、typecheck 与 iOS/Android Expo export，完成本地提交 `feat: 实现原生端单条知识修订体验`

## 10. 全链路验证与收尾

- [ ] 10.1 后端全量运行 `backend/.venv/bin/pytest backend/tests` 与 `backend/.venv/bin/ruff check backend/app backend/tests`，修复本 change 引入的失败和未解释 warning
- [ ] 10.2 移动端全量运行 `npm test -- --runInBand`、`npm run lint`、`npm run typecheck`、iOS/Android Expo export，Jest 正常退出且无新增未解释 `act`/open handle warning
- [ ] 10.3 运行 Alembic fresh SQLite upgrade、downgrade→upgrade；可用时验证 MySQL 8 迁移、约束、并发确认与撤销语义
- [ ] 10.4 用真实 API 走查：合法发起/生成/编辑/diff/确认/历史恢复/撤销、模型失败、越权、Evidence 失效、基线过期、网络幂等和后续版本阻止撤销；保存 curl、状态码、数据库版本与 Evidence 结果
- [ ] 10.5 在真实 RN 页面以 390×844 主尺寸和 360×800、412×915 扩展尺寸保存指令、草稿、差异、确认、applied、撤销、undone、冲突与错误截图；实际检查 iOS/Android 系统键盘、安全区、动态字体、长正文、底栏和读屏，无法验证项明确记录
- [ ] 10.6 运行 `git diff --check`、`openspec validate add-knowledge-agent-entry-revision --strict` 与 `openspec validate --all --strict`，核对 proposal/specs/design/tasks、原型偏离、AI 边界和 Workspace 隔离
- [ ] 10.7 将测试数量、curl、迁移、截图、设备、可观测记录、未验证项和剩余差异写入 change 的 `validation/validation.md`，逐项勾选实际完成任务
- [ ] 10.8 对实现做独立代码审查，重点检查客户端不可伪造 target/Evidence/diff、事务原子性、rollback 后对象状态、幂等并发、版本滚动和撤销 Evidence 精确性；修复后再次全量验证并本地提交
- [ ] 10.9 向用户逐条说明遗留问题、原因与影响，获同意后再登记 `docs/discussions/Grove后续优化清单.md`；等待用户手动验收通过后再归档、push 或 merge
