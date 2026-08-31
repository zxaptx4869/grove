## 1. 开工基线与前置同步

- [x] 1.1 阅读 `AGENTS.md`、本 change 全部工件、相关主规格、产品专题、移动原型对应片段，以及 `openspec-apply-change` 与 `grove-ui-conventions` 完整说明，确认本轮只做只读结构化 Entry 查找
- [x] 1.2 确认用户单独修复的三个前置问题（EntryVersion 字段长度、Revision edit/cancel 并发、Candidate rollback 后刷新对象）已经合入当前分支；若未合入则停止并汇报，不在本 change 重复或绕开
- [x] 1.3 记录当前后端 pytest/ruff、移动 Jest/lint/typecheck、iOS/Android Expo export 与 `openspec validate --all --strict` 基线；先区分既有失败与本 change 回归
- [x] 1.4 检查 Run/Message 迁移、结果序列化、游标、混合召回、关键词搜索、Entry 详情、Conversation controller 与消息归并实现，列出复用函数和兼容边界，不通过内部 HTTP 复用后端服务
- [x] 1.5 按 `design.md` 提取原型知识行、当前 AnswerCard/ModeSheet/Composer/CitationSheet 的视觉基线，写入 `validation/visual-baseline.md`，包括元素顺序、字号/行高、间距、边框、徽标、44×44 触控、Sheet、键盘、安全区和有意偏离
- [x] 1.6 运行 `openspec validate add-knowledge-agent-structured-entry-search --strict`，完成基线本地提交 `docs: 核对知识 Agent 结构化查找基线`

## 2. Run 协议、数据模型与迁移

- [x] 2.1 在后端常量与 Pydantic schema 中增加 `ResultMode=auto|answer|entries`、`ResultCompleteness=complete|limited|unknown`、结果项/结果集/分页响应；所有文本、列表和分页 limit 设置服务端约束
- [x] 2.2 扩展 `KnowledgeAgentRun` 的 request/actual result mode 与有界 `entry_result_json`，保持 `run_kind=answer` 和旧行按 answer 兼容，不修改既有 Candidate/Revision operation Run 语义
- [x] 2.3 新增 SQLite/MySQL 8 兼容 Alembic 迁移，检查 String 长度、Text 最大序列化字节、索引与 upgrade/downgrade；不得回填或改写历史 answer_json
- [x] 2.4 扩展 Run/Message/Conversation 输出与提交请求：默认 result mode 为 auto，重复 `client_message_id` 返回首次模式，首屏结构化结果随 Run 返回
- [x] 2.5 补模型、schema、旧行兼容、非法枚举/长度/limit、fresh SQLite、downgrade→upgrade 与 MySQL 字段长度测试
- [x] 2.6 运行本组定向 pytest、`backend/.venv/bin/ruff check backend/app backend/tests` 和 Alembic 验证，完成本地提交 `feat: 建立知识 Agent 结构化结果协议`

## 3. 结果形态路由与可观测性

- [x] 3.1 新增 PydanticAI 结构化结果形态路由，只接收 standalone query、范围标签和必要上下文，输出 answer/entries；不得接收或生成 Workspace、Project、Node、Entry 授权参数
- [x] 3.2 在上下文决策后接入 result route：clarify 直接结束；显式 answer/entries 跳过路由；entries 跳过 answer mode、调查、Evidence 和回答模型
- [x] 3.3 新增 `result_mode_route` purpose、模型调用与 fallback summary，记录真实 provider/model/is_fallback/error/duration；未配置、超时、异常和非法结构显式回退 answer
- [x] 3.4 保证 request answer mode 在 entries 路径仍可审计但 actual answer mode 为空，进度步骤只展示“判断结果形式/查找正式知识/整理结果”等可验证状态
- [x] 3.5 补 auto 两类路由、显式覆盖、clarify、路由失败/非法输出、取消边界、旧客户端默认和无隐藏关键词路由测试
- [x] 3.6 运行路由/Run 定向 pytest 与 ruff，完成本地提交 `feat: 增加知识 Agent 结果形态路由`

## 4. 有界 Entry 搜索与稳定结果快照

- [x] 4.1 实现 `execute_structured_entry_search` 服务，复用 RunToolContext 与现有召回/重排，按 owner/Workspace/项目复验并只保留正式 Entry；模型不得决定范围或对象 id
- [x] 4.2 实现按 Entry id 去重与稳定排序，批量加载 Project/Node/Evidence 数量避免 N+1；Workspace 结果逐项保存项目归属，目录仅作定位信息
- [x] 4.3 从正式 Entry 装配有界标题、摘要、类型、更新时间、来源数和可选可验证 match hint；不保存完整正文、Source 原文、prompt、伪相关度或模型编造理由
- [x] 4.4 集中配置候选/结果/摘要/JSON 字节上限，序列化前拒绝超限；明确 complete/limited/unknown、returned_count、warning 与 has_more 的独立语义
- [x] 4.5 在同一终态事务保存兼容助手摘要、actual result mode、结果 JSON、Run completed/partial/failed、fallback 与活动槽；空结果正常完成，partial 保留合法项，失败/取消不提交半份快照或推进工作集
- [x] 4.6 补 Workspace/项目隔离、跨用户/Workspace、Candidate 排除、范围外召回、去重/排序、字段命中与纯语义无 hint、空/limited/unknown、JSON 上限、事务回滚、取消与崩溃恢复测试
- [x] 4.7 运行搜索/Worker 定向 pytest 与 ruff，完成本地提交 `feat: 持久化有界正式知识查找结果`

## 5. 结果分页、历史恢复与工作集边界

- [ ] 5.1 新增 `GET /api/knowledge-agent/runs/{run_id}/entry-results`：按 owner + Workspace + Conversation + Run 读取同一持久快照，支持服务端限制的 limit 和绑定 run/schema/offset 的不透明游标
- [ ] 5.2 对游标篡改、跨 Run/用户/Workspace 使用、越界和非 entries Run 返回稳定 400/404；分页不得重新搜索或因当前数据库变化改写历史快照
- [ ] 5.3 Message Page/Run 查询批量归并实际结果形态与首屏结果，避免 N+1；旧 Run、旧响应和兼容助手摘要按设计兜底
- [ ] 5.4 打开结果详情复用当前 Entry API 并重新校验权限；通过 snapshot updated_at/指纹表达当前、已变化或不可用，不把历史快照当当前数据
- [ ] 5.5 确保 entries Run 无论 continue/new_topic、命中多少或分页多少都不创建 output context version、不切换活动工作集；模式纠正使用新消息而非修改旧 Run
- [ ] 5.6 补首屏/后续页、稳定顺序、重复/跳过、游标篡改、历史分页、重启恢复、Entry 后续更新/移动/删除、工作集不推进和幂等提交测试
- [ ] 5.7 用开发后端 `curl` 验证新增提交字段、Run 轮询和结果分页端点的 401/200/4xx 而非 404，运行本组 pytest/ruff，完成本地提交 `feat: 支持知识查找结果分页与恢复`

## 6. 原生领域协议与控制器

- [ ] 6.1 扩展 mobile 类型、snake/camel API 映射、query keys、adapters 与错误分类，兼容旧响应缺少 result mode/entry result 时继续渲染 AnswerCard
- [ ] 6.2 扩展 ModeSelection、ModeSheet 与 Composer payload/chip：结果形式 auto/answer/entries 只作用下一条，发送成功复位，失败保留用户选择
- [ ] 6.3 在 Conversation controller 归并首屏结果、分页页与 Run override，按 entry id 去重追加；切换会话、退出登录和刷新历史时清除错误/游标串线
- [ ] 6.4 实现分页加载/重试、详情查询及失效；下一页网络失败保留已加载项，不重新提交原问题或重跑搜索
- [ ] 6.5 实现模式纠正：将原问题填回 Composer 并预设相反 result mode，不自动发送、不复用旧 client_message_id、不修改历史 Run
- [ ] 6.6 补 API 映射、模式复位/失败保留、旧协议、消息归并、分页去重、会话切换、详情失效、纠正不自动发送和 active Run 冲突测试
- [ ] 6.7 运行移动定向 Jest、`npm run lint` 与 `npm run typecheck`，完成本地提交 `feat: 接入原生端结构化知识查找协议`

## 7. 原生 Entry 结果界面与原型对齐

- [ ] 7.1 实现 `EntryResultsCard` 与扁平 `EntryResultRow`：找到数量、范围、完整性、正式知识 Badge、标题、项目/目录、摘要、类型、来源数、更新时间和可选 match hint；不做卡片套卡片
- [ ] 7.2 实现 loading、empty、partial、failed、cancelled、limited/unknown 和分页状态；错误留在结果区域，已有项不因分页错误消失，动态文案不导致固定控件跳动
- [ ] 7.3 实现 `EntryResultSheet`：当前 Entry 完整正文、归属、类型、更新时间、来源摘要、加载/更新/不可用状态、关闭与焦点归还；不得出现修订、勾选或批量动作
- [ ] 7.4 在 AnswerCard 增加低强调“列出相关知识”，在结果卡增加“改为综合回答”；两者只预填 Composer 与 mode chip，保持原消息滚动位置和键盘行为
- [ ] 7.5 严格按 visual baseline 对齐元素顺序、字号、行高、间距、边框、圆角、徽标和按钮，不复制原型 HTML/CSS；有意偏离必须回写 design/validation，不以框架默认值代替
- [ ] 7.6 补组件测试：Workspace/项目结果、长标题/摘要、空目录、跨项目、30 条分页、完整性文案、分页失败、详情更新/404、44×44 触控、辅助名称、动态字体和不出现多选/修订/批量文案
- [ ] 7.7 运行移动全量 Jest（不得 `--forceExit`）、lint、typecheck、iOS/Android Expo export，完成本地提交 `feat: 实现原生端正式知识结果列表`

## 8. 全链路验证与独立审查

- [ ] 8.1 后端全量运行 `backend/.venv/bin/pytest backend/tests` 与 `backend/.venv/bin/ruff check backend/app backend/tests`，修复本 change 引入的失败和未解释 warning
- [ ] 8.2 移动端全量运行 `cd mobile && npm test -- --runInBand && npm run lint && npm run typecheck`，Jest 正常退出且无新增未解释 act/open handle warning
- [ ] 8.3 运行 iOS/Android Expo export；在可用环境验证 fresh SQLite、downgrade→upgrade 和 MySQL 8 迁移、String/Text 长度、分页与并发终态语义，无法验证项不得勾选并需明确记录
- [ ] 8.4 用真实 API/模型走查：auto 两类路由、显式覆盖、路由 fallback、Workspace/项目查找、空/limited/partial、历史恢复、分页、取消、越权、Entry 更新/删除及工作集不推进；保存状态码、数据库结果和可观测记录
- [ ] 8.5 在真实 RN 页面以 390×844 主尺寸及 360×800、412×915 扩展尺寸保存综合回答、Entry 结果、跨项目、空/limited/分页错误、详情更新/不可用与模式纠正截图；实际检查 iOS/Android 系统键盘、安全区、长内容、动态字体、底栏和读屏，无法验证项明确记录
- [ ] 8.6 运行 `git diff --check`、`openspec validate add-knowledge-agent-structured-entry-search --strict` 与 `openspec validate --all --strict`，核对 proposal/specs/design/tasks、AI 边界、Workspace 隔离、MySQL 兼容与原型偏离
- [ ] 8.7 将测试数量、curl、迁移、截图、设备、可观测记录、未验证项和剩余差异写入 `validation/validation.md`，只勾选真实完成任务
- [ ] 8.8 做独立代码审查，重点检查客户端不能伪造范围/Entry/游标/完整性、result/answer mode 优先级、JSON 边界、rollback 后 ORM 状态、工作集不推进、旧客户端兼容、分页和移动长列表性能；修复后再次全量验证并本地提交

## 9. 用户验收与收尾

- [ ] 9.1 向用户逐条说明遗留问题、原因与影响；获同意后再登记 `docs/discussions/Grove后续优化清单.md`
- [ ] 9.2 保持 change 为 active、本地分支可提交但不 push/merge/archive，等待用户在真实 App 手动验收自动路由、结果卡、分页、详情和模式纠正
- [ ] 9.3 用户明确验收通过后，按 `openspec-archive-change` 同步主规格并归档，复跑严格校验、最终本地提交；再次获得用户确认后才 push 与合并
