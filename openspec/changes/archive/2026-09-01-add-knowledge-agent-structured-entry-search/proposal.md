## Why

Knowledge Agent 已能围绕正式知识生成带引用的综合回答，但用户表达“帮我找出某条或几条知识”时，当前仍返回回答与引用条，不能稳定呈现可逐条查看的正式 Entry 对象，也无法明确说明结果是否还有更多。单 Entry 修订已经建立安全写入闭环，现在需要先补齐结构化对象查找，作为后续对象选择和多 Entry 整理的只读底座。

## What Changes

- 为普通对话消息增加 `auto / answer / entries` 结果形态请求；默认 `auto` 由独立、可观测的结构化路由判断“回答问题”或“查找 Entry”，路由失败显式回退综合回答。
- 在现有只读 answer Run 内持久化实际结果形态；`entries` 形态复用当前 Workspace/项目范围与正式知识搜索，只返回当前范围内已确认 Entry，不生成一段重复的综合回答。
- 返回稳定的结构化 Entry 结果集：标题、正文摘要、项目、目录、类型、更新时间、来源数量、匹配线索、生成时快照与当前可用状态；Workspace 范围逐项显示项目归属。
- 对结果数量、服务端上限、是否还有更多和“未承诺穷尽”作明确表达；支持从同一 Run 分页读取已经持久化的结果，不把 top-k 相关结果包装成“全部知识”。
- 结构化查找结果、实际模式、路由降级和范围快照随 Conversation 历史恢复；结果 Run 不因搜索命中自动推进事实工作集。
- 原生 App 在对话中展示与综合回答不同的 Entry 结果卡和列表状态，支持打开当前 Entry 详情、加载更多、重试，并允许用户将自动路由结果显式改为综合回答或 Entry 列表后重新提交。
- 严格按照已确认移动原型的 Grove 主题、卡片密度、对象层级、键盘、安全区和三尺寸基线实现；原型未覆盖的结构化结果卡在 `design.md` 中记录新增基线和有意偏离。

### Non-Goals

- 不做多选、跨消息持久选择集、批量修订、重复合并、冲突批处理、移动或删除 Entry。
- 不扩大现有单 Entry 修订的合法目标；本 change 的搜索结果卡不直接提供“修订这条知识”。
- 不创建 Candidate、Entry、Source 或目录，不让只读查找绕过人工确认边界。
- 不做目录节点级范围、手机 Web 业务界面、Web Knowledge Agent 入口或移动端“知识”栏目重建。
- 不引入联网搜索、模型常识补齐、向量基础设施替换或无限分页/后台持续查找。

## Capabilities

### New Capabilities

- `knowledge-agent-structured-entry-search`: 对话中的结果形态路由、受范围约束的结构化 Entry 结果集、完整性表达、持久化分页与恢复。
- `native-knowledge-agent-entry-results`: 原生 App 的 Entry 查找结果卡、详情、分页、模式纠正及移动端状态与可访问性。

### Modified Capabilities

- `knowledge-agent-conversation`: 消息提交与历史协议增加请求/实际结果形态及结构化 Entry 结果恢复。
- `knowledge-agent-run`: answer Run 增加可恢复的结果形态路由、结构化结果终态、取消/降级与原子提交语义。
- `knowledge-agent-working-set`: 结构化搜索命中不会自动变成事实工作集；显式切换结果形态也必须遵循原有主题与证据边界。

## Impact

- 后端：Knowledge Agent Run/Message schema、持久化字段与 Alembic 迁移、结果形态路由 Agent、正式 Entry 搜索与结果快照服务、Conversation/Run API、Worker 执行与可观测记录。
- 原生 App：领域类型、API/adapter/controller、Mode Sheet、消息线程、结构化 Entry 结果列表与详情 Sheet、分页/恢复/错误状态及测试。
- 数据库：为 Run 增加请求/实际结果形态和结构化结果 JSON（或等价持久化结构）；迁移必须兼容 SQLite 与 MySQL 8，旧 Run 默认按综合回答读取。
- 规格：新增结构化 Entry 查找和原生结果展示能力，并修改 Conversation、Run 与 Working Set 契约。
- 不新增第三方依赖；继续复用现有 AIProvider/PydanticAI、混合召回、Workspace 隔离和原生主题组件。
