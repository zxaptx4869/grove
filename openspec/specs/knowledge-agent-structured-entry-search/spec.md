# knowledge-agent-structured-entry-search Specification

## Purpose
TBD - created by archiving change add-knowledge-agent-structured-entry-search. Update Purpose after archive.
## Requirements
### Requirement: 每条普通消息明确请求与实际结果形态
系统 MUST 为普通 answer Run 接受 `auto`、`answer`、`entries` 三种 `result_mode`，默认 `auto`；系统 MUST 分开持久化请求形态与实际形态。`auto` MUST 在上下文决策得到独立问题后，由结构化结果形态路由判断返回综合回答或 Entry 结果；显式 `answer`/`entries` MUST 跳过自动路由且不得被模型改写。

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

### Requirement: 结构化查找只返回可信范围内的正式 Entry
结构化 Entry 查找 MUST 只使用 Run 固化的 owner、Workspace 和可选项目范围，并复用服务端受控正式知识召回；模型或客户端 MUST NOT 指定授权范围、目录节点范围或任意 Entry id。结果 MUST 排除 Candidate、Draft、Extraction、已删除对象和范围外 Entry。

#### Scenario: Workspace 范围查找
- **WHEN** Workspace 范围 Run 查找某一主题
- **THEN** 结果可以包含当前 Workspace 多个项目的正式 Entry，并逐项返回项目归属

#### Scenario: 项目范围查找
- **WHEN** 项目范围 Run 查找某一主题
- **THEN** 所有结果都属于该项目，目录路径仅用于定位而不改变范围

#### Scenario: 越权对象被召回或猜测
- **WHEN** 召回候选或模型输出包含其他 Workspace、其他用户或项目范围外 Entry
- **THEN** 服务端在形成结果前丢弃该对象、记录拒绝摘要且不泄露其字段或是否存在

#### Scenario: 待确认内容不进入结果
- **WHEN** 查询主题同时命中 pending Candidate 与正式 Entry
- **THEN** Entry 结果集只包含正式 Entry，不把 AI 候选标成知识对象

### Requirement: Entry 结果集是持久化对象快照而不是回答引用
系统 MUST 为 `entries` 结果持久化结构化结果集；每项 MUST 至少包含 Entry id、标题、长度受限正文摘要、项目、目录路径、知识类型、更新时间、来源数量、可选匹配线索和结果生成时快照。结果项 MUST 标识为正式知识对象，但结果排序或匹配说明本身 MUST NOT 被标为正式知识、Citation 或 Source Evidence。

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

### Requirement: 结果数量与完整性必须诚实且有界
系统 MUST 对单次结构化查找的候选数、持久化结果数、单页数和摘要长度设置服务端上限，并返回 `complete`、`limited` 或 `unknown` 的完整性状态、已找到数量、当前页数量与 `has_more`。只有搜索后端能够证明在本次查询语义和范围内没有更多匹配时才能返回 `complete`；达到预算、top-k 或候选上限 MUST 返回 `limited`，部分工具异常无法判断时 MUST 返回 `unknown`。

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

### Requirement: 结构化结果分页、恢复与重试保持同一 Run 语义
系统 MUST 通过 owner + Workspace + Conversation + Run 校验读取结构化结果页；游标 MUST 不透明、绑定原 Run 与稳定偏移并拒绝篡改。消息历史和 Run 查询 MUST 返回实际结果形态与首屏结果摘要，使原生 App 重启、向前分页或前后台切换后恢复同一结果，而不是重新提交查询。

#### Scenario: 重启后恢复结果卡
- **WHEN** App 在 Entry 查找完成后退出并重新打开 Conversation
- **THEN** 历史消息关联同一 Run，首屏结果、范围快照、完整性和分页位置可重新读取

#### Scenario: 篡改结果游标
- **WHEN** 客户端把其他 Run 的游标用于当前结果或修改游标内容
- **THEN** 系统拒绝请求且不返回任何 Entry 快照

#### Scenario: 网络重试重复提交
- **WHEN** 同一 `client_message_id` 以不同 result_mode 重复提交
- **THEN** 系统返回首次创建的 Run 与首次请求形态，不再次路由或生成第二个结果集

#### Scenario: 结果生成部分失败
- **WHEN** 搜索或结果装配只完成部分对象
- **THEN** 系统保留合法结果、标记 Run/结果为 partial 或 unknown、显示受影响阶段并允许重新提问，不把失败项伪装成已完成

### Requirement: 结构化查找不自动产生知识操作或事实工作集
Entry 结果集 MUST 是只读对象查找结果。搜索命中、分页、打开详情或切换显示形态 MUST NOT 创建 Candidate、Draft、Entry、Source、版本或目录变更，也 MUST NOT 自动把结果项写入 Conversation 事实工作集。普通 Composer 中疑似增删改文字仍不得绕过既有显式操作入口。

#### Scenario: 找到结果后未做其他动作
- **WHEN** 用户查看、分页或关闭 Entry 结果列表
- **THEN** 正式知识和当前活动工作集均不改变

#### Scenario: 结果列表中讨论修改
- **WHEN** 用户通过普通 Composer 说“这些都改一下”但未进入未来的结构化批量操作
- **THEN** 系统继续按只读消息处理或要求澄清，不直接修改任何 Entry

#### Scenario: 从结果详情查看当前 Entry
- **WHEN** 用户打开某条结果详情
- **THEN** 系统只读取并展示当前正式 Entry；本 change 不提供从结果卡直接修订、勾选或批量执行入口

