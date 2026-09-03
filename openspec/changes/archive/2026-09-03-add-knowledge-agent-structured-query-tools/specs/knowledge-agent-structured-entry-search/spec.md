## MODIFIED Requirements

### Requirement: 每条普通消息明确请求与实际结果形态
系统 MUST 为普通 answer Run 接受 `auto`、`answer`、`entries` 三种 `result_mode`，默认 `auto`；系统 MUST 分开持久化请求形态与实际形态。`auto` MUST 在上下文决策得到独立问题后，由结构化结果形态路由判断返回综合回答或 Entry 结果；查找对象、结构化筛选、计数、排序、分组或这些需求的组合可以路由为 `entries`。显式 `answer`/`entries` MUST 跳过自动结果形态路由且不得被模型改写，但 `entries` 内部仍可执行受限结构化查询规划。

#### Scenario: 自动判断为查找对象
- **WHEN** 用户询问“帮我找出个人健康项目里和血压有关的知识”且未覆盖结果形态
- **THEN** Run 保存 `request_result_mode=auto`、`actual_result_mode=entries` 并进入结构化 Entry 查找执行图

#### Scenario: 自动判断为综合回答
- **WHEN** 用户询问“这些血压记录说明了什么”且未覆盖结果形态
- **THEN** Run 保存 `actual_result_mode=answer` 并继续既有 quick 或 investigate 回答路径

#### Scenario: 用户显式覆盖结果形态
- **WHEN** 用户对下一条消息明确选择“知识列表”或“综合回答”
- **THEN** 系统使用该显式形态，不调用结果形态路由，并把覆盖值随该消息和 Run 保存

#### Scenario: 结果形态路由失败
- **WHEN** `auto` 路由未配置、超时、调用失败或输出非法结构
- **THEN** 系统显式记录 provider/model/fallback/error，安全回退 `answer`，不得静默伪装为成功路由或凭关键词执行隐藏写操作

#### Scenario: 自动判断为结构化统计
- **WHEN** 用户询问“最近半年有多少条个人经验，按月分组并列出最近五条”且未覆盖结果形态
- **THEN** 系统可以将实际结果形态设为 `entries`，再由受限结构化查询计划表达统计、分组和列表，不让结果形态路由直接生成数字

### Requirement: Entry 结果集是持久化对象快照而不是回答引用
系统 MUST 为 `entries` 结果持久化版本化结构化结果集；v2 结果 MUST 保存规范化集合摘要、排序、各输出完整性、受限 count/group_count 块和可选 Entry 项。每个 Entry 项 MUST 至少包含 Entry id、标题、长度受限正文摘要、项目、目录路径、知识类型、更新时间、来源数量、可选匹配线索和结果生成时快照。统计、分组、排序或匹配说明 MUST 标识为本 Run 的查询结果，不得被标为正式知识、Citation 或 Source Evidence。

#### Scenario: 成功返回多条 Entry
- **WHEN** 受控搜索找到多条合法正式知识
- **THEN** Run 不生成重复综合回答，而是保存有稳定顺序和去重 Entry id 的结构化结果项

#### Scenario: Workspace 结果展示归属
- **WHEN** 同一结果集包含多个项目的 Entry
- **THEN** 每张结果卡都有项目名与目录路径，用户无需根据当前对话范围猜测归属

#### Scenario: 匹配线索不可确定
- **WHEN** 语义召回无法给出可验证的字段命中位置
- **THEN** 结果可以省略匹配线索并展示 Entry 摘要，不得让模型编造“命中原因”或伪精确相关度

#### Scenario: 历史结果对应对象后来变化
- **WHEN** 用户重开历史 Run，而某个 Entry 已更新、移动或删除
- **THEN** 历史列表保留生成时快照；打开对象时重新校验当前 owner/Workspace/范围并显示当前内容、已变化或当前不可用，不把旧快照冒充当前 Entry

#### Scenario: 统计与列表保存在同一结果快照
- **WHEN** 同一计划请求精确计数、按类型分组和最近若干 Entry
- **THEN** v2 快照保存共享集合摘要、各聚合块、稳定 Entry 项和分别派生的完整性，历史恢复不重新运行查询

#### Scenario: 旧客户端读取 v2 结果
- **WHEN** 不识别 v2 聚合字段的旧客户端读取包含 Entry 项的结果
- **THEN** API 保留既有必需字段和助手兼容摘要，使旧客户端仍能展示有界 Entry 列表而不把未知统计编入正文

### Requirement: 结果数量与完整性必须诚实且有界
系统 MUST 对结构化计划输出数、工具调用数、候选数、持久化 Entry 数、单页数、聚合桶数、执行时间和 JSON 大小设置服务端上限，并为共享集合及每个 count、group_count、entries 输出返回 `complete`、`limited` 或 `unknown`。只有不含语义召回且数据库能证明授权集合已完整执行时，精确计数或分组才能标记 `complete`；达到 top-k、候选、列表或桶预算 MUST 标记受影响输出为 `limited`，部分工具异常无法判断时 MUST 标记 `unknown`。

#### Scenario: 已持久化结果还有下一页
- **WHEN** 当前页未展示完本 Run 已持久化的结果项
- **THEN** 响应返回不透明 `next_cursor` 和 `has_more=true`，后续页只读取同一快照且不重新运行搜索

#### Scenario: 达到召回上限
- **WHEN** 召回在服务端候选或结果上限停止
- **THEN** 结果标记 `limited` 并说明可能还有更多，客户端不得显示“全部结果”或“已穷尽”

#### Scenario: 本页结束但整体未穷尽
- **WHEN** 已展示完持久化结果但完整性为 `limited` 或 `unknown`
- **THEN** `has_more=false` 仅表示本次快照没有下一页，界面仍提示可缩小条件重新查找，不制造无限后台查找

#### Scenario: 空结果正常完成
- **WHEN** 搜索在当前范围正常完成且没有合法 Entry
- **THEN** Run 返回空结果集及当前完整性状态，说明没有找到匹配知识，不生成虚假回答或引用

#### Scenario: 结构化计数可以证明完整
- **WHEN** count 只使用受控类型和时间条件、授权范围查询正常完成且未触发执行预算
- **THEN** count 完整性为 complete，并与有界 Entry 展示数量分开返回

#### Scenario: 语义相关集合不能宣称精确总数
- **WHEN** count 或 group_count 的共享集合包含 semantic_query
- **THEN** 对应聚合标记 limited 或 unknown，只表达本次有界匹配集合，不显示为范围内全部相关知识
