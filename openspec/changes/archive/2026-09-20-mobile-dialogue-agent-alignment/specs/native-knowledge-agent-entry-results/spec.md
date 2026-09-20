## MODIFIED Requirements

### Requirement: 原生对话明确区分综合回答与 Entry 查找结果
原生 App MUST 按正式 dialogue blocks 区分文本、项目列表、目录列表、知识列表、统计和明确 Entry 对象；所有块与列表项 MUST 保持服务端原序和生成时范围。项目或目录项 MUST NOT 提供知识正文展开，知识列表只有在列表项携带明确 Entry 标识时才能读取当前正文；客户端 MUST NOT 把计划、统计、排序说明或匹配项标成 Evidence。

#### Scenario: 知识列表
- **WHEN** list 块明确包含 Entry 对象
- **THEN** thread 按服务端原序显示带稳定序号的紧凑知识项，并为带明确 Entry 标识的项提供当前正文详情入口

#### Scenario: 项目列表
- **WHEN** list 块表示项目集合
- **THEN** thread 显示项目名称和服务端提供的信息，不显示 Entry 正文入口

#### Scenario: 目录列表
- **WHEN** list 块表示目录集合
- **THEN** thread 显示目录路径和服务端提供的信息，不把目录当知识或 Evidence

#### Scenario: Workspace 跨项目结果
- **WHEN** 知识列表来自 Workspace 全部知识且条目包含项目归属
- **THEN** 每项按服务端元数据展示项目归属，列表头不把某一个项目误标为整个结果范围


#### Scenario: 自动返回 Entry 列表
- **WHEN** `actual_result_mode=entries` 的 Run 成功完成且只有 Entry 列表输出
- **THEN** thread 显示“找到 N 条相关知识”及 Entry 卡列表，不先输出一段重复的综合描述

#### Scenario: 自动返回综合回答
- **WHEN** `actual_result_mode=answer`
- **THEN** App 继续使用现有结构化回答、引用、调查摘要与冲突界面，不混入 Entry 结果卡语义

#### Scenario: 自动返回统计与 Entry 列表
- **WHEN** `actual_result_mode=entries` 的 v2 结果包含 count、group_count 和 entries
- **THEN** thread 先展示结构化范围/筛选与统计，再展示排序说明和 Entry 卡，不生成重复 AI 综合正文
### Requirement: Entry 结果卡提供稳定扫描信息与当前对象详情
每个明确 Entry 列表项 MUST 以标题为主，独立紧凑展示服务端提供的项目/目录归属；列表 MUST NOT 显示正文 `summary/excerpt`。服务端提供的 direct/indirect 性质与关联说明 MUST 保持准确并独立表达，不能把它改写为知识总结。动态长标题、空目录或跨项目归属 MUST 不造成横向溢出。点击带明确 Entry 标识的项 MUST 打开底部只读详情并按需调用现有 Entry GET；快速读取 MUST 直接呈现正文而不闪现瞬时加载弹层，读取持续时加载、失败重试和当前不可访问状态 MUST 在详情内显示，且不得改变列表顺序和序号。详情面板 MUST 按当前单条 Entry 内容自适应高度并受视口最大高度约束，不得沿用同批其他 Entry 的高度。

#### Scenario: 紧凑列表信息
- **WHEN** 知识项同时包含归属、正文摘要和关联说明
- **THEN** 列表只显示标题、简短归属与绿色关联性质/理由，不显示正文摘要，不改变服务端顺序和编号

#### Scenario: 首次打开仍可用的 Entry
- **WHEN** 用户首次点击当前仍有权限且带明确标识的 Entry 列表项
- **THEN** 页面只读取该 Entry；快速返回时从底部直接呈现正文，读取持续超过短暂展示阈值时才在详情内显示加载状态，成功后以知识标题和正文为主体，弱化更新时间并展示“关联来源”

#### Scenario: 不同长度 Entry 依内容定高
- **WHEN** 用户依次打开同一回答中正文长度不同的 Entry
- **THEN** 每次详情高度只由当前 Entry 内容和视口上限决定，短内容下方不因同批长内容保留大块空白，长内容在达到上限后内部滚动

#### Scenario: 关闭并再次打开
- **WHEN** 用户关闭详情后再次点击同一项
- **THEN** 主对话保持原阅读位置，是否复用同页已取结果由查询缓存决定，不预取其他 Entry

#### Scenario: 当前 Entry 与回答快照不同
- **WHEN** 当前只读接口返回的正文或更新时间与回答块快照不同
- **THEN** 详情以当前 GET 结果和弱化的更新时间表达当前版本，不把它冒充回答生成时快照，也不重写列表块

#### Scenario: Entry 当前不可用
- **WHEN** Entry 已删除、移出当前 Workspace 或权限校验失败
- **THEN** 详情显示“该知识当前不可访问”，不泄露内容、不删除历史列表项，也不提供写操作

#### Scenario: 读取失败后重试
- **WHEN** 单个 Entry 的只读请求因网络或暂时错误失败
- **THEN** 详情保留所选列表快照并显示重试，其他列表项与整轮回答不受影响

#### Scenario: 项目或目录项不读取 Entry
- **WHEN** list 块为项目或目录，或知识项缺少明确 Entry 标识
- **THEN** 客户端不打开 Entry 详情、不调用 Entry GET，也不从自然语言猜测对象标识

#### Scenario: 详情只读且不推进 Agent
- **WHEN** 用户打开或关闭 Entry 详情
- **THEN** 客户端最多调用该 Entry 的只读 GET，不提交聊天消息、不调用模型、不注入上下文，也不出现引用条、修订或候选保存入口



#### Scenario: 打开仍可用的结果
- **WHEN** 用户点击一张当前仍有权限的 Entry 卡
- **THEN** Sheet 展示当前正式知识完整内容、项目/目录、类型、更新时间与来源摘要，并允许关闭返回原滚动位置

#### Scenario: Entry 已变化
- **WHEN** 当前 Entry 与结果快照的更新时间或内容不同
- **THEN** Sheet 显示当前内容并提示“结果生成后已更新”，历史卡仍保留原快照语义### Requirement: 原生 Entry 结果严格遵循移动原型与可访问性基线
原生 App MUST 复用当前 Grove 主题、原创 Agent 图标、Card/Button、ConversationScreen 和现有键盘避让规则；正式实现 MUST NOT 复制原型 HTML/CSS/静态数据。结果列表和底部详情 MUST 在 360×800、390×844、412×915 下无非预期遮挡或横向溢出，打开、关闭和重试控件具有辅助名称、稳定触控尺寸和非颜色状态。详情正文 SHOULD 从 16sp、24–26 行高开始核对并支持系统字体缩放；滑入效果 MUST 只作用于详情，系统减少动态效果时 MUST 停用非必要动画。

详情遮罩 MUST 原地淡入淡出，只有底部面板上下移动；关闭动画完成前 MUST 保持 Modal 对背景点击的拦截。没有拖拽行为时 MUST NOT 显示拖拽横条。关闭按钮、遮罩和 Android 系统返回均可关闭详情，长正文在面板内部滚动，其他共享 Sheet 的既有展示语义不得被详情动效意外改变。

底部详情入场 MUST 同时等待原生 Modal 已显示和当前面板已完成有效布局；就绪前面板 MUST 保持不可见，入场位移 MUST 依据当前面板实测高度而非整屏高度。每次打开只可启动一次入场，重复布局、查询刷新、父级重渲染、减少动态效果异步就绪及过期动画回调 MUST NOT 重播入场或影响下一次打开。入场开始时的 loading、正文或错误内容 MUST 在入场完成前保持稳定；期间到达的查询结果在入场完成后再通过局部布局过渡显示，避免内容高度变化与滑入同时发生；系统减少动态效果时 MUST 直接更新而不执行该过渡。

#### Scenario: 三尺寸长结果走查
- **WHEN** 三种目标尺寸展示长标题、长摘要、多个项目、长正文和读取错误
- **THEN** 顶栏、thread、Composer、键盘、底栏与安全区不互相遮挡，消息区可滚动且列表原序稳定

#### Scenario: 原生窗口与面板布局乱序就绪
- **WHEN** Modal `onShow` 与面板首次有效 `onLayout` 以任意顺序到达
- **THEN** 客户端在两者均就绪前不展示或启动面板，只在本次打开中启动一次基于实测面板高度的入场

#### Scenario: 入场期间查询结果变化
- **WHEN** 详情以慢请求 loading 开始入场，或缓存内容在入场期间刷新
- **THEN** 本次入场保持开始时的内容和外框，入场完成后才显示最新查询状态，且不重新播放入场

#### Scenario: 使用读屏浏览结果
- **WHEN** 用户通过辅助技术访问知识列表
- **THEN** 每项读出序号、标题、项目/目录和详情可用状态，打开、关闭与重试具有明确辅助名称

#### Scenario: 知识写操作不抢跑
- **WHEN** 正式页面渲染知识列表或当前 Entry 正文
- **THEN** 不出现整理、保存、修订、撤销、勾选、批量操作或确认应用文案

## REMOVED Requirements


#### Scenario: 多 Entry 操作不抢跑
- **WHEN** 正式页面渲染结构化查找结果
- **THEN** 不出现勾选、全选、批量修订、合并、移动、删除或确认执行文案
### Requirement: 用户可以在发送前覆盖结果形态并纠正自动判断
**Reason**: 正式 adapter 不执行移动端旧 `result_mode` 控件，保留入口会误导用户并形成第二套路由。

**Migration**: 用户用自然语言提出所需结果，客户端按服务端 dialogue blocks 展示；不提供旧结果纠正重提。


#### Scenario: 显式选择知识列表
- **WHEN** 用户在发送前选择“知识列表”
- **THEN** Composer 显示可移除设置，提交携带 `result_mode=entries`，发送成功后本地选择恢复 `auto`

#### Scenario: 把列表改为综合回答
- **WHEN** 用户在 Entry 结果中点击“改为综合回答”
- **THEN** App 以新的 `client_message_id` 和 `result_mode=answer` 直接重新提交原问题并创建新 Run，历史结果不被修改；对话存在活动 Run 时按冲突提示处理，不产生重复消息

#### Scenario: 把回答改为知识列表
- **WHEN** 用户在合格的综合回答中点击“列出相关知识”
- **THEN** App 以新的 `client_message_id` 和 `result_mode=entries` 直接重新提交原问题并创建新 Run，历史结果不被修改；对话存在活动 Run 时按冲突提示处理，不产生重复消息

#### Scenario: 来源用户消息未加载或当前范围已变化
- **WHEN** 历史卡对应的用户消息不在客户端当前分页，或 Conversation 已切换范围与活动主题
- **THEN** App 仍携带 `source_run_id` 提交，服务端恢复来源 Run 的原问题、范围与输入工作集，不静默无响应，也不改用当前上下文
### Requirement: 分页、空结果和部分失败在原位可恢复
**Reason**: 旧 v1/v2 Entry Result 专用分页合同不再作为正式移动端输出主合同。

**Migration**: list 与 insufficient 块按服务端本轮交付内容展示；单 Entry 当前正文读取可独立重试。


#### Scenario: 加载下一页
- **WHEN** 结果响应 `has_more=true` 且用户点击“加载更多”
- **THEN** App 使用原 Run 的不透明游标追加去重结果，按钮进入禁用加载态且不重新提交原问题

#### Scenario: 下一页请求失败
- **WHEN** 已展示首屏结果但下一页网络请求失败
- **THEN** 已有卡片保留，列表底部显示错误与重试，不把整个 Run 改成空或失败

#### Scenario: 结果未承诺穷尽
- **WHEN** 完整性为 `limited` 或 `unknown` 且当前快照已无下一页
- **THEN** 页面明确提示“本次结果可能不完整，可缩小条件再找”，不显示不可执行的无限加载按钮

#### Scenario: 没有找到结果
- **WHEN** Entry 结果集为空
- **THEN** 页面说明当前范围没有找到匹配知识，并提供“修改问题”动作，不显示空白卡或虚假推荐
### Requirement: 原生端按完整性展示结构化筛选与聚合
**Reason**: 客户端不再维护旧 v2 Entry Result 专用筛选与聚合适配器。

**Migration**: 正式 statistic 与 list 块按其公开字段和原序展示，不从卡片数量推断统计。


#### Scenario: 精确计数与最近五条
- **WHEN** 服务端返回 complete count=23 和按更新时间倒序的五条 Entry
- **THEN** 界面显示“共 23 条”及“最近更新 5 条”，不把五张卡误写成总数

#### Scenario: 有限语义统计
- **WHEN** count 来自包含 semantic_query 的 limited 集合
- **THEN** 界面说明统计只覆盖本次匹配结果，不显示“全部 23 条”或其他精确全集语义

#### Scenario: 分组包含未标注信息性质
- **WHEN** group_count 返回 `info_nature=unspecified` 桶
- **THEN** App 使用“未标注”用户文案并显示服务端计数，不暴露内部枚举或丢弃该桶

#### Scenario: 聚合块过长
- **WHEN** 分组结果达到服务端桶上限或在目标视口不能一次展示完
- **THEN** 组件保持有界滚动/展开和截断提示，不造成横向溢出或遮挡 Composer
### Requirement: 原生端兼容 v1/v2 历史结果并保持当前对象复验
**Reason**: 移动端尚未上线，不为旧测试 Run 保留复杂 v1/v2 渲染双轨。

**Migration**: 旧 Run 仅在有扁平 answer 时做简单文本回退；当前正式链路历史按 dialogue blocks 恢复。

#### Scenario: 恢复旧 v1 结果
- **WHEN** 历史 Run 只有 v1 query、items 和 completeness
- **THEN** App 按现有 Entry 列表渲染，不显示空统计区域、未知 schema 错误或猜测筛选条件

#### Scenario: 恢复 v2 组合结果
- **WHEN** App 重启后加载包含结构化计划摘要、聚合和分页 Entry 的 v2 Run
- **THEN** App 恢复相同统计、排序、首屏项和完整性，且不重新提交消息或重跑查询

#### Scenario: v2 Entry 后来变化
- **WHEN** 用户从历史统计结果打开一条后来更新或删除的 Entry
- **THEN** 聚合保持历史快照语义，详情重新鉴权并显示当前内容、已变化或当前不可用
