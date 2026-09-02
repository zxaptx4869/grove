# Grove 后续优化清单

> 本文档是多次讨论产出的后续优化总览（非正式笔记，不参与 OpenSpec 主规格）。
> 每条给出背景与触发条件；实施时按 OpenSpec 流程新建 change。已有专项文档的用链接引用，避免重复维护。

## A. 检索与语义质量

1. **向量化（embedding + 阈值规则兜底判断）**
   - 背景：路线 A（确定性召回 + LLM 重排）对「同义替换 / 无语面重叠」会漏召回；关系判断不稳定根因在 LLM 判断层。
   - 方向：embedding 召回 + 相似度阈值规则接管大部分重复判断，LLM 只处理模糊区间。
   - 前置：需真实数据标注集标定阈值。
   - 参考：[Embedding与语义检索.md](Embedding与语义检索.md)、[LLM与模型调用.md](LLM与模型调用.md)。

2. **召回质量标注集（Recall@10 / Precision@10）**
   - 背景：验证路线 A 的召回缺口有多大，是向量化的决策依据。
   - 前置：真实装修数据集 + 人工标注语义相关对。

3. **语义搜索效果优化**
   - 背景：当前语义搜索对同义不同词效果一般（路线 A 固有局限）。
   - 方向：与向量化同步评估，不单独上向量。

16. **关系判断阈值的正式标定**
    - 背景：当前 duplicate/new 阈值（T_high=0.85 / T_low=0.45）基于现有 107 条候选的历史判定粗标，样本小（duplicate 9 条、supplement 5 条）；余弦分布依赖具体模型。
    - 方向：结合 A2 正式标注集重新标定阈值；上线后持续用行为信号（用户接受/修改/拒绝关系建议）校准。
    - 来源：2026-08-26，add-embedding-vector-retrieval。

17. **稀疏向量混合召回**
    - 背景：doubao-embedding-vision 对纯文本支持稀疏向量输出；当前只用稠密向量 + 原有确定性召回。
    - 方向：稀疏向量补充字面精确匹配召回，与稠密向量 / 关键词路径混合；需评估存储与检索成本。
    - 触发条件：关键词精确命中仍有漏召回，或语义检索需要更强的专名 / 型号匹配时。
    - 来源：2026-08-26，add-embedding-vector-retrieval。

18. **相关知识弱相关折叠展示**
    - 背景：跨域弱相关（如「瓷砖光泽 ↔ 灯光光斑」，余弦 0.3~0.45）与真相关条目分数带重叠，阈值切不干净（提高阈值会误伤真瓷砖条目）。
    - 方向：低于某阈值的推荐条目标记「弱相关」并折叠 / 置后，保留召回、改善观感；不做硬删除。
    - 结论：暂缓（2026-08-26 决定先不改，此类条目相关性有一定合理性）。

19. **Entry 级语义索引状态徽标**
    - 背景：索引状态目前只在项目首页与模型设置页聚合展示，单条知识的「索引中 / 失败」不可见。
    - 方向：知识空间卡片 / 列表加小徽标；需控制噪音（当时认为聚合展示够用，暂缓）。
    - 触发条件：用户频繁遇到「单条知识语义搜不到」且需要定位原因时。
    - 来源：2026-08-26，add-embedding-vector-retrieval。

## B. AI 阅读（Reader）

4. **保存为知识异步化**
   - 背景：保存时同步跑目录推荐 + 关系判断（两次 LLM），弹窗延迟关闭。
   - 方向：保存接口只建候选立即返回，路由/关系丢后台任务（复用项目 worker 模式）。
   - 触发条件：保存变高频或「慢」成为明显痛点。
   - 参考：[Reader保存为知识异步化.md](Reader保存为知识异步化.md)。

5. **保存回答的专用重复判断**
   - 背景：综合型回答（引用多条 Entry）的 duplicate / supplement 边界模糊，判断不稳定。
   - 方向：规定「内容与所引 Entry 高度重合时默认标重复，明显新增才允许 new/supplement」。

6. **节点问答范围切换**
   - 背景：节点范围 = 当前节点 + 子树，用户容易误解「范围只有节点自身」。
   - 方向：提供「仅本节点 / 含子树」两个选项，或在选择后展示覆盖节点数与知识数。

20. **引用 quote 完整句兜底**
    - 背景：AI 阅读引用偶见截断在句中的 quote（如「…但」），可读性差。
    - 方向：引用校验时对 quote 做完整句兜底（补齐到句号 / 换行），或要求模型输出完整句引用。
    - 优先级：低。
    - 来源：2026-08-26，add-embedding-vector-retrieval。

## C. 模型与稳定性

7. **模型参数规范 + 换模型接入点**
   - 背景：各环节 temperature/max_tokens 建议值已讨论并部分落地，但未形成统一规范。
   - 方向：整理各 Agent 的参数配置表；换模型时在 `ai_models.py` 工厂扩展 provider。
   - 参考：[LLM与模型调用.md](LLM与模型调用.md)。

13. **AI 对话中「讨论 vs 输出内容」的显式意图**
   - 背景：修订建议对话中讨论问题时模型仍会硬给草稿。
   - 状态：已实施（2026-08-23，change `add-ai-revision-discussion-intent`）——输出结构显式二选一（`intent: discuss | propose`），提示词收回为一句；仍误判再升级为 KnowStruct 同款工具调用。
   - 参考：[AI对话中讨论与内容输出的区分.md](AI对话中讨论与内容输出的区分.md)。

14. **修订建议结构化 grounding（逐条来源标注）**
   - 背景：AI 修订建议目前用「（AI 补充）」文字标注 + 草稿整体 `external_supplemented` 标记，无法精确到每条修改的来源。
   - 方向：结构化输出每条修改的 grounding（「来自材料（引用某证据）」或「AI 知识补充」），UI 逐条展示，实现精确到条目的溯源。
   - 触发条件：真实使用中需要精确溯源，或外部补充占比升高时。
   - 参考：`openspec/changes/archive/2026-08-23-add-ai-revision-external-knowledge/design.md` 的 Open Questions。

21. **模型名下拉选择 / 格式校验**
    - 背景：手工输入模型名容易出错（如 `doubao-embedding-vision-25121500` 多打 00 导致批量 404）；现有探针可拦截，但体验仍依赖用户自查。
    - 方向：模型设置里用下拉选择（列出方舟已开通模型）或对模型名做格式校验 / 提示。
    - 来源：2026-08-26，add-embedding-vector-retrieval。

22. **多模型向量空间并存**
    - 背景：当前单模型设计，切换模型即全量重建；无法同时支持文本模型与多模态模型（如图搜、图文混搜）。
    - 方向：按模型分别存向量空间（entry_embeddings 已带 model 字段），按场景路由到对应模型检索。
    - 触发条件：出现图搜 / 图文检索等跨模态需求时。
    - 来源：2026-08-26，add-embedding-vector-retrieval。

## D. 工程债务

8. **ESLint 既有问题**
   - 背景：`DirectoryDraftDialog.tsx` 有 2 个 `react-hooks/set-state-in-effect` 错误，`npm run lint` 无法全绿。
   - 方向：单独小 fix 清理（与业务 change 无关）。
   - 状态：已清理（2026-08-23，渲染期派生状态替代 effect 内 setState）。

9. **主规格 Purpose 占位**
   - 背景：归档后多个 spec 的 Purpose 仍是 `TBD - created by archiving...`。
   - 方向：补一句用途描述（纯文档，随手可做）。
   - 状态：已补齐（2026-08-23，28 个主规格）。

## E. 产品演进

10. **多轮对话**
    - 背景：MVP 是单轮问答（消息化接口已预留扩展）。
    - 档位：B = 前端聊天界面 + 每次独立检索（轻量）；C = 会话持久化 + 历史管理 + 指代理解（完整）。
    - 触发条件：真实使用证明「多轮」是刚需。

11. **思维导图目录浏览**
    - 背景：P1 最后一个 change（`add-directory-mind-map-view`）。
    - 范围：目录浏览模式 + 节点侧栏知识，非编辑器。

12. **真实数据验证**
    - 背景：多个「不能靠讨论定死」的问题需要真实使用回答。
    - 验证项：AI 阅读使用占比、保存为知识的真实价值、多轮是否刚需、语义检索召回缺口。

15. **Entry 内容轻量 Markdown 渲染**
    - 背景：AI 修订建议会产出 markdown 标记（如 `*加粗*`），当前知识视图全部按纯文本渲染，标记原样显示；曾设想让内容「按情况有轻有重」（简单句保持纯文本，方法/经验用加粗、列表、标题结构化）。
    - 方向（2026-08-23 讨论的推荐方案，未实施）：子集 = 加粗/斜体/有序无序列表/2-3 级标题/行内代码 + 链接（新窗口打开）；存储 Markdown 原文、展示时渲染；卡片紧凑渲染 + 高度渐变遮罩截断；编辑框原文 + 轻量工具栏（加粗/列表/标题/链接）；搜索命中时降级纯文本高亮；旧内容零迁移（无标记即纯文本）。
    - 结论：暂缓。当前感觉得不偿失（收益有限、渲染/高亮/截断都要处理兼容性）；以后用户真实使用中格式化内容变多或可读性成痛点时再议。

## F. 知识 Agent 底座

23. **租约恢复与慢执行的并发重入**
    - 背景：`recover_stale_runs` 会把超过租约的 `processing` Run 重新入队；若原 Worker 只是搜索/回答较慢仍在执行，同一 Run 会被两个 Worker 并发执行，观测记录（工具调用、模型调用）会重复，最终回答以最后一次提交为准。
    - 影响：工具全部只读、终态事务提交，不会污染正式知识，但可观测记录失真；多实例部署前需处理。
    - 方向：领取时记录租约标识/心跳，恢复前确认原执行者已退出；或恢复时跳过仍持有进程内租约的 Run。
    - 来源：2026-08-28，add-knowledge-agent-foundation（代码评审发现）。

24. **可观测聚合对 TOOL_ERROR 的降级语义**
    - 背景：`run_fallback_summary` 把工具状态 `TOOL_ERROR` 计为 `is_fallback=False`，若出现纯错误工具阶段，`has_fallback` 可能为 False，聚合摘要低估问题。
    - 影响：当前 `record_tool_result` 尚未产生 `TOOL_ERROR`，暂不影响线上；后续新增错误路径时需一并修正。
    - 来源：2026-08-28，add-knowledge-agent-foundation（代码评审发现）。
    - 状态：已修复。2026-08-28，add-knowledge-agent-continuous-follow-up 任务 1.2 将工具降级汇总改为 `ok`/正常 `empty` 不算 fallback，`partial`/`denied`/`unavailable`/`error` 均进入受影响阶段且 `error` 不再被标为正常。

25. **同范围切换产生多余系统消息**
    - 背景：`change_scope` 未比较新旧范围，切换到与当前相同的范围也会追加一条 `scope_change` 系统消息。
    - 影响：轻微噪音；客户端按消息流展示时会看到无意义的范围事件。
    - 来源：2026-08-28，add-knowledge-agent-foundation（代码评审发现）。

26. **知识 Agent 租约配置缺少文档**
    - 背景：`KNOWLEDGE_AGENT_LEASE_SECONDS` 有代码默认值（300），但 `backend/.env.example` 未收录说明。
    - 影响：部署者无法从模板得知该配置；属纯文档缺口。
    - 来源：2026-08-28，add-knowledge-agent-foundation（代码评审发现）。

27. **提交接口并发竞态下的状态码**
    - 背景：`submit_message_endpoint` 在调用提交服务前计算 `created`，并发重复提交时可能对已存在的消息返回 201 而非 200。
    - 影响：客户端主要依赖返回体中的消息与 Run 标识，状态码偏差影响很小；如需严格语义可在服务内返回 created 标记。
    - 来源：2026-08-28，add-knowledge-agent-foundation（代码评审发现）。

28. **连续追问自动分类准确率评估与规则短路**
    - 背景：`auto` 上下文决策依赖模型判断，尚无真实追问样本验证准确率；误判时用户只能用 `continue`/`new_topic` 显式纠正。
    - 方向：客户端接入后收集真实追问样本，评估分类准确率；达到足够水平后再考虑确定性规则短路（例如指代明显、主题高度一致时直接判 continue），本 change 不预设阈值。
    - 来源：2026-08-28，add-knowledge-agent-continuous-follow-up（design 开放问题）。

29. **工作集客户端展示与单项管理**
    - 背景：工作集目前只返回主题标签与版本摘要，客户端无法可视化「当前主题基于哪些 Entry」或手动移除某条。
    - 方向：在 Web/App 对话交互 change 中提供活动工作集展示与单项移除入口；后端首版保留不可变版本审计语义。
    - 来源：2026-08-28，add-knowledge-agent-continuous-follow-up（design 开放问题）。

30. **已归档底座迁移的 SQLite 主键类型修复留痕**
    - 背景：fresh SQLite 经 alembic 建表时，主键列若为 `BIGINT` 不会被当作 `INTEGER PRIMARY KEY` rowid 别名，插入时 `id` 不自增报 NOT NULL；本 change 走查暴露该缺陷。
    - 处理：已在 add-knowledge-agent-continuous-follow-up 中把底座迁移 `a0b1c2d3e4f5` 与新迁移 `b1c2d3e4f5a6` 的 `_bigint()` 改为 `sa.BigInteger().with_variant(sa.Integer(), "sqlite")`，并补自增回归测试。
    - 影响：属于对已归档迁移文件的一行修改，仅影响未来 fresh SQLite 安装；此处留痕以便追溯迁移历史差异。
    - 来源：2026-08-28，add-knowledge-agent-continuous-follow-up（API 走查发现）。

31. **离线环境深度调查不可演示**
    - 背景：未配置文本模型密钥时，路由/控制器固定离线降级，强制 `investigate` 立即以 `insufficient` 停止（1 轮、0 查询）；用户无法在无密钥环境体验多轮补查。
    - 影响：属于设计的安全降级，不影响正确性；仅演示与联调体验受限。
    - 方向：后续可增加离线确定性控制器（类似上下文 demo），让无密钥环境也能走通调查闭环。
    - 来源：2026-08-28，add-knowledge-agent-bounded-investigation（验收走查）。

32. **崩溃恢复重置未完成轮次可能重复控制器计费**
    - 背景：恢复时对未完成轮次采用「安全重置」（删除轮次行与计划查询后从该轮重来），崩溃前已发起的控制器调用可能重复执行并计费。
    - 影响：设计已接受（恢复/预算观测可见），但多轮长调查下成本略增。
    - 方向：后续优化为幂等重放已持久化计划（跳过控制器、直接复用查询行执行工具）。
    - 来源：2026-08-28，add-knowledge-agent-bounded-investigation（代码评审）。

33. **调查摘要 JSON 文本列不可强查询**
    - 背景：调查的 coverage/gaps/conflicts 摘要存 JSON 文本列，仅用于展示与下一轮控制器上下文，无法对轮次观察做结构化分析/查询。
    - 影响：当前够用；如需按缺口/冲突统计或审计分析，需拆为规范化子表。
    - 来源：2026-08-28，add-knowledge-agent-bounded-investigation（design 既定取舍）。

34. **MySQL downgrade 未在真实实例验证**
    - 背景：一次性 MySQL 8 实例只验证了 upgrade 到 head、唯一约束、级联、取消与恢复；downgrade 回滚路径仅由迁移代码保证。
    - 影响：正式环境变更窗口内建议再执行一次 downgrade 回滚验证。
    - 来源：2026-08-28，add-knowledge-agent-bounded-investigation（MySQL 验证）。

35. **调查控制器查询长度与详情接口文本长度限制（已修复留痕）**
    - 背景：`validate_controller_output` 只截断 coverage/gaps/conflicts/reason，查询文本不限长度，超长查询会写入 Text 列并原样出现在 `GET /runs/{id}/investigation`。
    - 处理：新增 `KNOWLEDGE_AGENT_INVESTIGATION_QUERY_CHARS=200` 并对查询确定性截断；轮次/查询数量天然受预算约束（≤3 轮、≤6 查询），详情接口文本长度随源头受限。
    - 来源：2026-08-28，add-knowledge-agent-bounded-investigation（代码评审发现，已修复）。

36. **调查检索曾用规范化文本（已修复留痕）**
    - 背景：规范化（去全部空格 + 小写）用于指纹去重，但执行搜索时误用了规范化文本，英文查询 "water test" 会以 "watertest" 检索，关键词召回降级；中文场景无影响。
    - 处理：检索改为使用清理后的原文（`original_query`），规范化文本仅用于指纹与去重，并补回归测试。
    - 来源：2026-08-28，add-knowledge-agent-bounded-investigation（代码评审发现，已修复）。

37. **调查无证据与 quick 无知识的 insufficient 状态差异**
    - 背景：quick 无相关知识返回 `completed + insufficient`，调查零证据返回 `partial + insufficient`；两者各有理由（调查已消耗轮次仍未获证据视为部分完成），但客户端展示需统一口径。
    - 影响：当前无客户端消费；后续对话 UI change 需按「实际模式 + 停止原因」统一展示语义。
    - 来源：2026-08-28，add-knowledge-agent-bounded-investigation（代码评审观察）。

38. **草稿整理范围从「本轮全部证据」收敛回「回答最终引用」**
    - 背景：为修复 v2 回答漏挂引用导致「厨房柜体用多层板」等正文结论丢失，d44254a 把草稿白名单从「最终 citations」放宽到「本 Run 目标项目内全部当前可核验 Evidence」。副作用：回答未展示、未引用的检索命中（如调查发现的 C）也可能被整理进草稿，用户会认为 Agent 悄悄扩大了整理范围（2026-08-30 会话验收反馈）。
    - 方向：回答 prompt v3 已强制每个要点至少挂一个句柄，漏挂概率大幅下降；候选方案是把草稿白名单改回「回答最终采用的 citations」，并保留「正文有依据但未挂引用」的回归测试；若 v3 后仍出现正文结论丢失，再评估以「回答展示内容」为准的替代放宽方案。
    - 结论：暂缓，登记待评估（2026-08-30 决定先不改，避免重新引入正文结论丢失问题）。
    - 来源：2026-08-30，add-knowledge-agent-candidate-drafting（d44254a 引入），会话验收反馈。

39. **结果形态路由命中率与真实模型质量需评测**
    - 背景：结构化查找的 auto 路由、embedding/rerank 与匹配线索在本 change 验证时处于离线环境，全部按 fallback 记录，未用真实模型评估命中率与质量。
    - 影响：自动路由误判会直接影响“综合回答 vs 知识列表”体验；limited 比例与匹配线索质量决定用户对结果完整性的信任。
    - 方向：配置真实密钥后按真实数据评测路由命中率、用户显式纠正比例、limited 占比与空结果比例，再决定是否调整路由提示词或服务端预算。
    - 来源：2026-09-01，add-knowledge-agent-structured-entry-search（验收走查，离线环境未验证）。

40. **MySQL 8 运行时迁移与分页并发终态未在本机验证**
    - 背景：本 change 的新迁移（String(8) 结果形态列、Text 结果 JSON）与分页/并发终态只在 SQLite 验证；本机无 MySQL 8/Docker 守护进程，未能做真实实例验证。
    - 影响：生产 MySQL 8 首次升级时存在未实测风险（字段长度、TEXT 字节边界、批量 ALTER、并发终态语义）。
    - 方向：在可用 MySQL 8 环境复跑 upgrade/downgrade、分页游标与并发终态测试；与既有「MySQL downgrade 未在真实实例验证」条目合并评估。
    - 来源：2026-09-01，add-knowledge-agent-structured-entry-search（验证记录）。

41. **结果详情来源仅展示标题与片段摘要，未提供 Attachment 原文预览**
    - 背景：`EntryResultSheet` 当前按只读边界展示来源标题与核验片段，未接入 Attachment 原文预览。
    - 影响：审阅结果时如需核对原文需另开入口，体验受限；不影响正确性与溯源。
    - 方向：后续在结果详情或引用弹窗复用现有 Attachment 原文能力，仍保持只读与权限校验。
    - 来源：2026-09-01，add-knowledge-agent-structured-entry-search（design 只读边界外的增强）。

42. **移动端结果卡未提供「在知识空间打开」定位跳转**
    - 背景：结构化查找结果卡只能打开当前 Entry 详情，不能跳转到 Web 知识空间对应目录浏览。
    - 影响：从对话“找到对象”到“在知识空间继续浏览”的连续性缺失；属端侧体验增强。
    - 方向：后续在结果详情或行操作提供知识空间定位入口，遵循端侧边界与深链策略。
    - 来源：2026-09-01，add-knowledge-agent-structured-entry-search（验收观察）。

43. **开发模式启动期 schema 一致性检查（防“代码比库新”运行期 500）**
    - 背景：真机排查发现 `uvicorn --reload` 热加载新模型列但开发库未迁移时，会话列表等接口运行期 500；README/AGENTS 已改为“启动前先 `alembic upgrade head` + 带迁移改动后手动升级”，但运行中 reload 仍可能短暂落后。
    - 影响：约定能覆盖大部分场景；若再出现“代码比库新”，仍是运行期 500 而非明确提示。
    - 方向：开发模式启动时做模型与数据库 schema 一致性检查，不一致时打印“请先运行 alembic upgrade head”并明确失败；生产不启用。
    - 来源：2026-09-01，add-knowledge-agent-structured-entry-search（真机排查，2026-09-01 会话确认登记）。

44. **Run/消息响应只返回结构化结果首屏**
    - 背景：当前 Run 与消息历史响应仍携带最多 30 条完整结果快照，移动端收到后再截取 6 条首屏；“加载更多”会从结果分页接口重新读取已传输的数据。
    - 影响：不影响结果正确性，但长会话会产生重复传输，分页在网络负载上的收益有限。
    - 方向：数据库继续保存完整不可变快照，Run/消息输出层只返回首屏条目和稳定的 `has_more/next_cursor`，后续页继续读取同一快照。
    - 来源：2026-09-01，add-knowledge-agent-structured-entry-search（代码审查，当前上限较小，延期优化）。

45. **开放讨论 basis 迁移的 MySQL 8 真实验证**
    - 背景：本 change 的 `knowledge_agent_runs` 依据字段迁移（request_basis_mode /
      planned_basis_strategy / answer_basis_json）只在 SQLite 执行过 upgrade/downgrade；
      本机没有可用 MySQL 8 实例。
    - 影响：生产 MySQL 8 首次升级存在未实测风险（batch ALTER、Text 列、旧行兼容）。
    - 方向：在可用 MySQL 8 环境复跑 upgrade/downgrade 与旧 Run 读取；与既有条目
      34/40 的 MySQL 验证合并评估。
    - 来源：2026-09-02，add-knowledge-agent-open-discussion（验收观察）。

46. **开放讨论完成态需真机与真实模型端到端补验**
    - 背景：真机验证环境无模型密钥时只能看到规划/回答的离线降级；三视口走查使用
      react-native-web 近似，未覆盖 iOS/Android 系统键盘、安全区与读屏焦点。
    - 影响：model-first/hybrid 的完成态展示与真机系统交互尚未端到端确认；不影响
      已自动化覆盖的正确性。
    - 方向：配置真实模型 key 后在真机/模拟器复核完成态依据概览与依据详情；核对
      键盘、安全区、读屏标签与像素级视觉，截图回填验收记录。
    - 来源：2026-09-02，add-knowledge-agent-open-discussion（验收观察）。

47. **依据规划的候选用户消息子集未单独持久化**
    - 背景：Run 只持久化 `planned_basis_strategy`，没有持久化 planner 选中的候选
      用户消息 ID；崩溃恢复用同一有界允许集合确定性重建，策略不漂移但原始候选
      子集不会原样回放。
    - 影响：恢复后的提示上下文可能与首次执行略有差异（均在服务端允许集合内），
      不影响范围隔离与依据真实性。
    - 方向：若需要恢复与首次执行严格一致，后续为 Run 增加内部 basis plan JSON
      列并随规划检查点提交。
    - 来源：2026-09-02，add-knowledge-agent-open-discussion（实现取舍）。

48. **依据详情“定位用户消息”为估算滚动**
    - 背景：原生依据详情里的“定位”按消息序号估算偏移滚动对话，不是像素精确。
    - 影响：长对话或加载更早历史后定位可能落在目标消息附近而非精确位置。
    - 方向：后续为消息行建立稳定 ref/索引后做精确滚动定位。
    - 来源：2026-09-02，add-knowledge-agent-open-discussion（实现取舍）。

49. **无引用 AI 即时回答下的“列出相关知识”入口易误导**
    - 背景：真机反馈：model-first 无引用回答下方仍显示“列出相关知识”，点击后
      把同一问题以知识列表模式重新搜索；用户容易误以为列表与回答来源相关。
    - 影响：不影响正确性，但“AI 即时回答/未使用知识库”语义与相邻入口的观感
      不一致，可能造成误解。
    - 方向：按有无引用/依据区分该入口：无引用开放回答可隐藏，或改用更明确的
      文案（如“查看知识库是否有相关记录”）并说明这是一次新的查找。
    - 来源：2026-09-02，add-knowledge-agent-open-discussion（真机反馈）。
