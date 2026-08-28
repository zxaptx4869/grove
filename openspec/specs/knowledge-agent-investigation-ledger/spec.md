# knowledge-agent-investigation-ledger Specification

## Purpose
TBD - created by archiving change add-knowledge-agent-bounded-investigation. Update Purpose after archive.
## Requirements
### Requirement: 调查账本归属当前 Run 且隔离
系统 MUST 将 Investigation、Round、Query 和账本对象永久归属到一个 Run，并冗余或可验证当前用户与 Workspace；所有读取 MUST 复验对话、Run、用户和 Workspace 所有权，项目范围账本 MUST NOT 包含其他项目对象。

#### Scenario: 读取当前 Run 调查详情
- **WHEN** 对话所有者在当前 Workspace 读取调查 Run
- **THEN** 系统返回该 Run 的轮次、查询和受限账本摘要

#### Scenario: 读取其他用户或 Workspace 调查
- **WHEN** 用户请求不属于当前用户或 Workspace 的调查详情
- **THEN** 系统返回 404 且不暴露调查是否存在

#### Scenario: 项目范围结果越界
- **WHEN** 某轮工具结果包含不再属于 Run 固化项目的对象
- **THEN** 账本拒绝加入该对象并记录不可用结果

### Requirement: 轮次与查询过程完整留痕
系统 MUST 按稳定轮次和顺序保存控制器动作、合法查询、查询规范化指纹、执行状态、结果计数、覆盖/缺口/冲突摘要及相关模型/工具调用归属；同一调查的轮次号和规范化查询 MUST 唯一。

#### Scenario: 成功提交调查轮次
- **WHEN** 一轮控制器和工具执行完成
- **THEN** 系统原子保存该轮动作、实际查询、增量计数、观察摘要与调用归属

#### Scenario: 重复写入同一查询
- **WHEN** 恢复或并发路径尝试在同一调查写入相同规范化查询
- **THEN** 唯一约束或应用幂等逻辑阻止重复记录和重复计数

#### Scenario: 工具部分失败
- **WHEN** 某查询的批量工具调用部分成功、部分失败
- **THEN** 账本分别记录成功增量、不可用对象和 partial 状态，而不把整轮伪装成完全正常

### Requirement: 已发现集合跨轮次去重并可重建
系统 MUST 基于已提交查询结果和 Evidence 重建当前 Run 的已发现集合，并按 Entry、Source/Attachment 与 Evidence 身份去重；后续轮次 MUST 能使用先前轮次发现的合法 Entry，但 MUST 重新复验其当前范围与可用性。

#### Scenario: 后续轮次读取先前 Entry
- **WHEN** 第二轮需要读取第一轮搜索发现且仍在范围内的 Entry
- **THEN** 系统将该 Entry 视为当前 Run 已发现对象并允许受控读取

#### Scenario: 多个查询命中同一 Entry
- **WHEN** 同轮或不同轮查询返回相同 Entry
- **THEN** 账本只计一个不同 Entry，同时保留必要的查询命中归属

#### Scenario: 恢复时重建集合
- **WHEN** Worker 根据已完成轮次恢复调查
- **THEN** 系统确定性重建已查询、已发现 Entry、Evidence 和剩余预算

#### Scenario: 先前发现对象后来失效
- **WHEN** 已发现 Entry 在后续读取前被删除、移出范围或来源不可用
- **THEN** 系统不继续使用其内容，账本记录不可用并从有效集合排除

### Requirement: 账本事实只能来自当前 Run Evidence
系统 MUST 只把当前 Run 重新读取并核验的 Evidence 作为最终事实依据；历史消息、历史工作集内容、历史 Run Evidence、控制器摘要和搜索片段 MUST NOT 被提升为可引用事实。

#### Scenario: 历史回答包含相关结论
- **WHEN** 控制器在有限历史中看到上一轮助手结论
- **THEN** 该结论只能辅助理解问题，不进入当前账本的可引用 Evidence 集合

#### Scenario: 工作集带来历史 Entry
- **WHEN** 调查使用输入工作集 Entry 作为种子
- **THEN** 系统重新读取其当前 Source/Attachment 并为当前 Run 生成 Evidence 后才能支持结论

#### Scenario: 控制器摘要提到新事实
- **WHEN** 控制器在 coverage 或 conflict 摘要中写入没有当前 Run Evidence 支持的事实
- **THEN** 最终综合不得把该摘要当作事实引用

### Requirement: 账本内容紧凑且不是正式知识
系统 MUST 对账本中的查询、覆盖、缺口、冲突和对象摘要实施数量与长度限制，只保存恢复与审计所需的 ID、指纹、状态和短摘要；调查账本 MUST NOT 创建或覆盖 Entry、Source、目录或其他正式知识。

#### Scenario: Attachment 内容很长
- **WHEN** 调查读取大体积 Attachment
- **THEN** 账本只保存 Evidence 定位与受限摘要，不复制整份原文

#### Scenario: 控制器返回超长摘要
- **WHEN** coverage、gaps 或 conflicts 超过服务端长度上限
- **THEN** 系统拒绝非法结构或确定性截断并记录该处理

#### Scenario: 调查正常完成
- **WHEN** Investigation 进入完成或不足终态
- **THEN** 系统只提交回答、引用和 Run 内审计状态，不自动写入正式知识

