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

### Requirement: Entry 结果卡提供紧凑扫描信息与底部只读详情
每个明确 Entry 列表项 MUST 以标题为主，独立紧凑展示服务端提供的项目/目录归属；正文 `summary/excerpt` 最多显示一行并在溢出时省略，没有摘要时 MUST NOT 补造。服务端提供的 direct/indirect 性质与关联说明 MUST 保持准确并与正文摘要分开，不能因摘要截断而丢失。动态长标题、空目录或跨项目归属 MUST 不造成横向溢出。点击带明确 Entry 标识的项 MUST 打开底部只读详情并按需调用现有 Entry GET；加载、失败重试和当前不可访问状态 MUST 在详情内显示，且不得改变列表顺序和序号。

#### Scenario: 紧凑列表信息
- **WHEN** 知识项同时包含归属、正文摘要和关联说明
- **THEN** 标题、归属、单行摘要与关联性质按独立层级展示，不拼接成长段小号灰字，也不改变服务端顺序和编号

#### Scenario: 首次打开仍可用的 Entry
- **WHEN** 用户首次点击当前仍有权限且带明确标识的 Entry 列表项
- **THEN** 页面从底部打开只读详情并显示加载状态，只读取该 Entry，成功后展示标题、当前正式知识正文、更新时间和当前来源信息

#### Scenario: 关闭并再次打开
- **WHEN** 用户关闭详情后再次点击同一项
- **THEN** 主对话保持原阅读位置，是否复用同页已取结果由查询缓存决定，不预取其他 Entry

#### Scenario: 当前 Entry 与回答快照不同
- **WHEN** 当前只读接口返回的正文或更新时间与回答块快照不同
- **THEN** 详情明确标注“当前知识内容”和更新时间，不把它冒充回答生成时快照，也不重写列表块

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

### Requirement: 原生 Entry 结果严格遵循移动原型与可访问性基线
原生 App MUST 复用当前 Grove 主题、原创 Agent 图标、Card/Button、ConversationScreen 和现有键盘避让规则；正式实现 MUST NOT 复制原型 HTML/CSS/静态数据。结果列表和底部详情 MUST 在 360×800、390×844、412×915 下无非预期遮挡或横向溢出，打开、关闭和重试控件具有辅助名称、稳定触控尺寸和非颜色状态。详情正文 SHOULD 从 16sp、24–26 行高开始核对并支持系统字体缩放；滑入效果 MUST 只作用于详情，系统减少动态效果时 MUST 停用非必要动画。

#### Scenario: 三尺寸长结果走查
- **WHEN** 三种目标尺寸展示长标题、长摘要、多个项目、长正文和读取错误
- **THEN** 顶栏、thread、Composer、键盘、底栏与安全区不互相遮挡，消息区可滚动且列表原序稳定

#### Scenario: 使用读屏浏览结果
- **WHEN** 用户通过辅助技术访问知识列表
- **THEN** 每项读出序号、标题、项目/目录和详情可用状态，打开、关闭与重试具有明确辅助名称

#### Scenario: 知识写操作不抢跑
- **WHEN** 正式页面渲染知识列表或当前 Entry 正文
- **THEN** 不出现整理、保存、修订、撤销、勾选、批量操作或确认应用文案

## REMOVED Requirements

### Requirement: 用户可以在发送前覆盖结果形态并纠正自动判断
**Reason**: 正式 adapter 不执行移动端旧 `result_mode` 控件，保留入口会误导用户并形成第二套路由。

**Migration**: 用户用自然语言提出所需结果，客户端按服务端 dialogue blocks 展示；不提供旧结果纠正重提。

### Requirement: 分页、空结果和部分失败在原位可恢复
**Reason**: 旧 v1/v2 Entry Result 专用分页合同不再作为正式移动端输出主合同。

**Migration**: list 与 insufficient 块按服务端本轮交付内容展示；单 Entry 当前正文读取可独立重试。

### Requirement: 原生端按完整性展示结构化筛选与聚合
**Reason**: 客户端不再维护旧 v2 Entry Result 专用筛选与聚合适配器。

**Migration**: 正式 statistic 与 list 块按其公开字段和原序展示，不从卡片数量推断统计。

### Requirement: 原生端兼容 v1/v2 历史结果并保持当前对象复验
**Reason**: 移动端尚未上线，不为旧测试 Run 保留复杂 v1/v2 渲染双轨。

**Migration**: 旧 Run 仅在有扁平 answer 时做简单文本回退；当前正式链路历史按 dialogue blocks 恢复。
