## Context

Knowledge Agent 当前的普通消息统一创建 `run_kind=answer` Run。执行器先做上下文决策，再选择 quick / investigate，最终保存 `KnowledgeAnswerOut` 到 `answer_json`；移动端 `AnswerCard` 负责综合回答、结构化要点、Citation、冲突和调查摘要。现有只读工具已经能按 Run 固化的 Workspace/项目范围混合召回正式 Entry，桌面关键词搜索也能覆盖标题、正文、目录和 Source 标题。

这个模型能回答“关于血压，我的知识有什么结论”，却不能准确表达“把相关的几条知识找出来”：引用只代表回答实际采用的 Evidence，不等于对象查找结果全集；用户也无法快速扫描 Entry 标题、项目、目录与摘要。单 Entry 修订已完成，但它只允许从回答最终 Citation 发起，本 change 不放宽这一证据边界。

约束如下：

- 结果范围仍只有当前 Workspace「全部知识」和一个具体项目，不增加目录范围。
- 结构化结果只包含正式 Entry；排序与匹配线索不是正式知识或 Citation。
- 搜索必须有界、可恢复且诚实表达完整性，不把 top-k 说成“全部”。
- 旧 Run、旧移动客户端与现有 quick / investigate 行为需要向后兼容。
- 原生 App 是本 change 唯一正式客户端；手机 Web 和 Web Reader 不在范围内。
- 产品原型没有完整的“对话内 Entry 结果列表”页面，但已有知识栏目的扁平 `knowledge-card`、对话卡、Sheet、主题与移动设备基线可复用为视觉依据。

## Goals / Non-Goals

**Goals:**

- 让用户默认用自然语言即可在综合回答和“找 Entry”之间获得合适结果，同时提供低成本显式纠正。
- 在现有 Run 生命周期内保存可分页、可恢复、按范围隔离的 Entry 结果快照。
- 返回适合扫描与打开的正式知识对象信息，并区分历史快照与当前 Entry。
- 复用现有搜索、Entry 详情、Conversation、Worker、可观测性和原生对话组件，不建立第二套知识模型。
- 为未来对象选择与多 Entry 操作建立清楚的只读结果协议，但不预建写操作。

**Non-Goals:**

- 不做勾选、选择集、多 Entry 合并、批量修订、移动、删除或目录调整。
- 不让结构化搜索结果直接成为单 Entry 修订目标，不改变 revision Evidence 白名单。
- 不把查找结果加入工作集，不支持“第三条”“把这些都改了”等隐式对象指代。
- 不重做搜索基础设施、引入外部搜索或承诺语义搜索穷尽所有可能相关对象。
- 不实现 Web 对话入口、移动知识栏目、手机 Web 或后台无限查找。

## Decisions

### 1. `result_mode` 与 `answer_mode` 分层，Run 类型保持 `answer`

普通消息新增：

```text
request_result_mode: auto | answer | entries
actual_result_mode:  answer | entries | null
```

`answer_mode=auto|quick|investigate` 只在 `actual_result_mode=answer` 时有意义。执行顺序为：

```text
上下文决策 / 独立问题改写
        ↓
结果形态路由（仅 request_result_mode=auto）
        ├─ answer  → 既有回答模式路由 → quick / investigate
        └─ entries → 有界 Entry 查找图
```

上下文决策若返回 clarify，Run 直接按既有澄清终态提交，不进行结果或回答形态路由。显式 result mode 跳过路由；`entries` 跳过 answer mode、调查、Evidence 与回答模型，`actual_answer_mode` 保持空。

继续使用 `run_kind=answer`，因为两种结果都来自同一条普通只读用户消息，复用同一上下文、范围、活动槽、取消和历史语义。新增 `entry_search` Run kind 会把“消息目的”与“输出表现”混为操作类型，并迫使 Worker/客户端复制大量 answer 生命周期代码，收益不足。

结果路由使用独立 PydanticAI 结构化输出，只接收服务端形成的 `standalone_query`、范围标签和最小必要上下文，不接收对象 id 或权限参数。新增 `PURPOSE_RESULT_MODE_ROUTE`；模型调用失败显式 fallback 到 `answer`。不使用关键词规则静默替代模型，以免“帮我找原因”和“帮我找 Entry”产生难以观察的误判。

### 2. 使用 Run 上的有界不可变结果快照，不新增结果表

`KnowledgeAgentRun` 增加 `request_result_mode`、`actual_result_mode` 与 `entry_result_json`（名称实现时可保持等价，但协议字段不得混进 `answer_json`）。结果 JSON 使用版本化 Pydantic schema，包含：

```text
schema_version
query
status: completed | partial
completeness: complete | limited | unknown
items[]
  entry_id
  title
  excerpt
  project_id / project_name
  node_id / node_path
  main_type / info_nature
  updated_at
  source_count
  match_hint? / matched_fields[]?
returned_count
candidate_limit
warning?
```

首版建议候选上限 50、持久化结果上限 30、默认页 6、最大页 12、摘要 240 字；具体值集中到 settings 并用边界测试锁定，禁止客户端扩大。30 条 × 有界摘要可安全落在 MySQL `TEXT` 与 SQLite Text 内，不保存完整 Entry 正文、Evidence 原文或 prompt。

选择 JSON 而不是结果项表的原因：结果是单 Run 的不可变展示快照，不参与正式关系、事务写入或跨 Run 查询；表模型会引入大量外键、删除语义和分页关联，但近期没有独立生命周期价值。未来若真实使用要求跨 Run 持久选择集，再建立独立 Selection/Collection 对象，不把历史结果快照原地升级成写模型。

迁移必须显式使用足够长度的字符串字段并验证 MySQL 8；旧行三个字段为空时，客户端按 `request_result_mode=auto`、`actual_result_mode=answer` 且无结构化结果兼容。

### 3. 查找图复用受控召回，但返回 Entry 对象而非 Evidence

新增独立 `execute_structured_entry_search` 服务，复用现有 RunToolContext、混合召回/关键词召回、embedding 与 rerank 能力；服务端完成范围过滤、正式状态过滤、按 Entry id 去重、稳定排序和快照装配。模型不提供 Workspace、project_id、node_id 或 Entry id。

结果项信息直接来自当前正式 Entry、Project、Node 和真实 Evidence 关系计数。`match_hint` 只能来自服务端可解释的字段命中或长度受限的正文命中片段；纯语义召回无法产生可靠命中位置时留空，不让结果路由或回答模型自由编造理由，也不展示伪精确相似度。

结构化查找不读取 Source Attachment 原文、不创建 Run Evidence、不调用最终回答模型，因此结果项不是 Citation。打开详情时复用 `/api/entries/{entry_id}` 重新读取当前 Entry 与 Evidence 来源摘要；历史卡始终保留生成时快照，详情通过 `updated_at`/字段指纹判断“已更新”，404 统一显示当前不可用。

备选方案是把每个 Entry 都生成 Evidence，以便直接修订。它会显著放大 Source 读取与 Evidence 预算，并把“找到对象”错误地等同于“回答采用了这些证据”，本轮拒绝。

### 4. 完整性和分页分成两个正交维度

结果集返回：

- `completeness=complete`：搜索实现能证明当前查询语义与范围内没有更多匹配；
- `limited`：命中候选、top-k 或结果上限，可能存在未进入快照的对象；
- `unknown`：搜索/重排部分失败或降级后无法判断；
- `has_more`：仅表示本次持久化快照还有未展示页。

因此 `has_more=false` 不等于 `complete`。首版不做一个 Run 内的无限追加搜索：达到快照末尾但结果有限时，引导用户缩小条件再发起新 Run。这样崩溃恢复和历史一致性简单，也不会让结果随数据库变化漂移。

新增 `GET /api/knowledge-agent/runs/{run_id}/entry-results?cursor=&limit=`。首屏结果随 `KnowledgeRunOut` 和 Message Page 返回；更多页通过不透明游标读取同一 JSON 快照。游标复用现有签名/编码约定并绑定 run id、owner、Workspace、结果 schema version 与 offset；越界或篡改返回稳定 400/404。客户端按 `entry_id` 去重追加，分页失败保留已有项。

### 5. 终态、恢复与兼容摘要沿用现有 Run 事务

entries 路径在最终事务一次提交：助手消息兼容摘要、Run status、actual result mode、entry result JSON、fallback summary、活动槽释放；不创建 Investigation 或输出工作集。无结果是正常 completed，工具部分失败但已有合法结果为 partial，没有可展示结果且关键工具失败为 failed。

助手消息保存短兼容文本，例如“找到 6 条相关正式知识，请使用支持结构化结果的客户端查看。”新移动端在识别 `actual_result_mode=entries` 时不重复显示这段文字，只渲染结果组件；旧客户端至少不会出现空白助手消息。先部署兼容后端，再发布新客户端。

Worker 恢复可以重新执行搜索，但只在最终事务提交快照；没有已提交半份结果。若同一 Run 已有合法终态结果，领取逻辑不得再次改写。取消检查放在结果路由前后、搜索批次和最终提交前，迟到搜索结果不写入。

### 6. 结果命中不推进工作集，纠正模式创建新消息

结构化结果不是事实回答，也没有最终有效 Citation，因此无论 context decision 是 continue 还是 new_topic，都不创建输出工作集版本，原活动工作集保持不变。历史结果 JSON 不参与后续事实回答；上下文改写只可读取用户问题与兼容助手摘要理解“再找几条”之类意图，不能把结果内容当事实。

当用户认为自动结果形态不合适时，移动端在答案卡/结果卡提供“列出相关知识 / 改为综合回答”纠正按钮；点击后以新的 `client_message_id`、来源 `source_run_id` 和相反的显式 `result_mode` 直接重新提交原问题（用户显式点击发起，不是后台静默行为）。服务端按同一用户、Workspace 与 Conversation 校验来源 Run，并恢复原用户消息、已固化的独立问题与上下文决策、生成时范围、请求上下文模式和输入工作集版本；客户端是否已加载原用户消息、当前对话范围、后来历史消息或当前活动工作集不得改变重提语义。新 Run 独立创建，历史结果不被修改，提交时不提前关闭当前活动工作集；对话存在活动 Run 时按冲突提示处理。如需修改措辞，用户可先编辑 Composer 再自行发送普通新问题。

### 7. 原生界面采用“一个结果容器 + 扁平 Entry 行”

**原型基线**

- 对应原型：`docs/prototypes/grove-mobile-agent-prototype.html` 的对话消息卡、知识栏目 `.knowledge-card` 扁平列表、范围 Sheet 与 Entry/Source Sheet。
- 主验收视口：390 × 844；扩展视口：360 × 800、412 × 915。
- 主题与组件：复用 `mobile/src/theme.ts`、`AgentIcon`、`Card`、`Sheet`、`AppButton`、`ConversationScreen`、`ModeSheet`、Composer mode chip 与现有键盘避让。
- 固定区域：沿用现有顶栏、消息 FlatList/ScrollView、Composer、输入聚焦时隐藏底栏、iOS/Android 唯一键盘避让负责人和安全区。

**采用的结构**

- thread 中使用一个 `EntryResultsCard`：顶部为“找到 N 条相关知识”、实际范围、完整性说明；主体是带分隔线的 `EntryResultRow`，不做卡片套卡片。
- 行内顺序保持稳定：正式知识 Badge → 标题 → 项目/目录 → 摘要 → 类型、来源数、更新时间 → 可选匹配线索。Workspace 结果始终显示项目；项目范围允许收敛重复项目名但详情仍显示。
- 点击一行打开 `EntryResultSheet`，用现有 `getEntryCurrent` 读取完整当前正文和 Evidence 来源标题；保留加载、不可用、已变化、关闭与焦点归还。
- 列表底部显示已加载数量、完整性文案、同快照“加载更多”或“修改条件再找”；分页错误就地重试，不 toast-only。
- `ModeSheet` 新增“结果形式”组选项；Composer 增加对应 override chip。Entry 结果页提供“改为综合回答”，合格 AnswerCard 提供低强调的“列出相关知识”，二者点击后直接以新消息提交原问题。

**有意偏离**

- 不直接复用知识栏目页面结构或导航；原因是本 change 的结果属于具体历史消息，必须保留 Run、范围与完整性。
- 不使用横向 Citation chip 展示结果；原因是 Entry 结果是可扫描对象列表，不是支持回答结论的 Source Evidence。
- 不在每行显示勾选框、修订、合并或批量动作；原因是选择集与多 Entry 写操作尚未定义，提前展示会制造不可兑现的能力。
- 不显示模型相关度百分比；原因是缺少可校准含义。只展示可验证字段命中或 Entry 摘要。

视觉实现前需量取原型知识行与当前 AnswerCard 的字号、行高、间距、边框、徽标、点击区域和 Sheet 顺序，并记录到 `validation/visual-baseline.md`。完成后使用真实 RN 页面在三尺寸走查长标题、跨项目、30 条结果、分页错误、空结果、键盘展开、动态字体、44×44 触控和读屏；Expo Web 只能补充，不能代替 iOS/Android。

### 8. 观测、测试与安全门禁

新增 `result_mode_route` 模型 purpose 和 `structured_entry_search` 工具调用摘要；记录实际 provider/model/fallback/error/duration、候选数、范围过滤数、去重数、最终结果数、完整性与截断原因，不记录整份 Entry 正文、结果 JSON 或原始 prompt。

后端测试至少覆盖：三种 result mode、路由失败、范围/owner 隔离、正式 Entry 过滤、Workspace 跨项目、去重与稳定排序、完整性、分页游标、空/partial/failed、取消/恢复、幂等、工作集不推进、旧行兼容、SQLite/MySQL 迁移。移动端覆盖协议映射、模式设置复位、消息恢复、列表/详情、分页追加与错误、模式纠正直接重发与新幂等键、失效对象、长内容、可访问性和旧响应兜底。

## Risks / Trade-offs

- [自动结果路由会误判“找原因”和“找 Entry”] → 独立结构化路由、显式 fallback、下一条消息模式覆盖和一键纠正重发；不因误判产生写操作。
- [语义搜索无法证明穷尽] → 将完整性与分页分离，top-k/预算上限一律 limited，不显示“全部”。
- [JSON 快照未来不适合持久选择] → 首版只读且有界；真实多 Entry 操作另建 Selection 对象，不复用历史 JSON 作为授权依据。
- [旧客户端看不到结果卡] → 助手消息保留短兼容摘要并先部署后端；新客户端识别结构化结果后抑制重复文本。
- [结果生成后 Entry 变化] → 列表明确是历史快照；打开时按当前权限重新读取，显示更新或不可用。
- [结果模式增加 ModeSheet 高度] → Sheet 必须可滚动并在 360×800 + 系统键盘/动态字体走查；不把三个维度挤成难懂的单行控件。
- [大结果 JSON 接近 MySQL TEXT 上限] → 服务端限制条数与摘要长度，序列化前断言字节上限，迁移和边界测试覆盖 MySQL 8。

## Migration Plan

1. 新增 Alembic 迁移与模型字段，保持 nullable/向后兼容；在 fresh SQLite 和 MySQL 8 验证 upgrade、downgrade→upgrade、字段长度与有界 JSON。
2. 部署后端 schema、Worker、结果 API 和兼容助手摘要；旧请求未传 `result_mode` 时按 auto，旧历史空字段按 answer 展示。
3. 发布原生客户端类型、控制器和界面；客户端对缺少 result mode/result JSON 的响应继续走现有 AnswerCard。
4. 观察 result route 命中率、用户显式纠正、limited 比例、空结果和 fallback；预算调整只修改服务端 settings 与测试，不改变完整性语义。
5. 回滚客户端时保留后端结果与兼容摘要；回滚后端代码前停止产生新 entries 结果。数据库 downgrade 只删除新增 Run 字段，不修改 Entry 或对话历史消息。

## Open Questions

- 无阻塞产品问题。实现阶段需基于现有混合召回接口确认哪类查询能安全标记 `complete`；无法证明时必须使用 `limited` 或 `unknown`，不得为了更好看的文案放宽规格。
- 多选与跨消息选择集、搜索结果直接修订、批量整理的授权和失效语义留给后续 change，本次不预留客户端假按钮或服务端写接口。
