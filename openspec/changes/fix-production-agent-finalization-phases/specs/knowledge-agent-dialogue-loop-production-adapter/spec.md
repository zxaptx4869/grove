## ADDED Requirements

### Requirement: 软阈值停止不得丢失可安全交付内容

统一 dialogue-loop 在输入投影达到 9000 软阈值但未达到 12000 硬上限时 MUST 停止新增搜索、读取和其他资料动作，并 MUST 允许既有无工具 finalizer 根据已确认对话、已授权材料及同轮已经通过对应内容边界检查的文本完成收尾。未筛选语义候选 MUST 保持不可展示、不可引用且不得被解释为空结果；完成状态 MUST 依据实际交付和剩余步骤决定，不得统一改为 `completed`。

#### Scenario: Run 13 整理请求在软阈值处安全收尾

- **WHEN** 首次请求投影 8295 并成功完成项目上下文和返回 5 条未筛选候选的搜索，下一求解请求投影 9290
- **THEN** 系统不再派发资料动作，而由无工具 finalizer 使用已确认对话解释不能直接保存正式 Entry 并可提供候选稿
- **AND** 回答不包含 5 条候选、列表块或“0 条结果”，终态按实际回答和未完成筛选判断

#### Scenario: 依赖候选的任务仍然部分完成

- **WHEN** 用户问题必须依赖 5 条语义候选才能回答，而软阈值在相关性选择前触发
- **THEN** 系统不把候选作为直接相关结果，不声称查无结果，并准确返回相关性筛选未完成及可恢复状态

#### Scenario: 硬上限和真实模型失败保持原保护

- **WHEN** 必要输入仍超过 12000 硬上限，或真实模型请求已经派发后由 Provider 失败
- **THEN** 系统分别按输入硬边界或真实模型失败停止，不以无工具收尾伪装成功，也不提高任何冻结预算

### Requirement: 未筛选候选续执行只恢复未完成步骤

任务依赖未筛选候选时，系统 MUST 保存最小 `relevance_selection` continuation，包括原问题、候选句柄及内容指纹、成功查询摘要、Workspace/用户/项目范围和对象校验引用。用户明确继续时 MUST 重新校验 Workspace、权限、项目范围、候选 Entry 和句柄内容，仅恢复相关性选择及其后的最终回答；成功搜索 MUST NOT 重复派发。校验失败 MUST 准确终止恢复且不得授权旧候选。

#### Scenario: 继续完成筛选而不重复搜索

- **WHEN** 有效的 `relevance_selection` continuation 保存了成功搜索和 5 条未筛选候选，用户说“继续”
- **THEN** 系统复用原候选完成逐项 direct/indirect/unrelated 选择，再按授权结果收尾
- **AND** 新增搜索次数为零，间接与不相关候选不进入答案

#### Scenario: 权限或范围变化使恢复失效

- **WHEN** continuation 保存后用户失去 Workspace/Entry 权限、项目范围变化或候选对象版本改变
- **THEN** 系统返回 `continuation_material_invalid`，不重新搜索、不展示候选且不把 Run 标记为完成

#### Scenario: 候选句柄失效

- **WHEN** continuation 的候选句柄缺失、指纹不一致或不再属于原成功查询
- **THEN** 系统拒绝恢复，不猜测替代句柄也不重新执行成功查询

### Requirement: 结构化输出兼容必须严格且可恢复

统一模型包装层 MAY 对唯一输出工具参数形如 `{"INVALID_JSON": "..."}` 的已知 Provider 包装执行一次确定性解包，但仅在内层字符串可由标准 JSON 解析器严格解析、顶层恰为受支持的 `DialogueAnswer`、完整合同校验通过时才可转换。系统 MUST NOT 使用宽松 JSON 修复、正则提取、补括号或放宽 schema；解析或授权校验失败时 MUST 保留已确认材料及 finalize-only continuation，并且继续只重试最终回答而不重复成功资料动作。现有模型请求和重试预算 MUST 保持不变。

#### Scenario: 外层包装但内层合法

- **WHEN** Provider 将完整合法的 `DialogueAnswer` 放进唯一 `INVALID_JSON` 字符串字段
- **THEN** 系统严格解析并按原合同验证，在不增加模型请求的情况下接受结果并记录兼容事件

#### Scenario: 真实 INVALID_JSON 内层损坏

- **WHEN** 2026-09-16 实验台真实响应的外层包含 `INVALID_JSON`，而内层六点补充文本在 JSON 第 1120 列附近因未转义引号而无法严格解析
- **THEN** 系统拒绝该输出，不修复或提取正文，保留已确认材料并公开合法的 finalize-only continuation

#### Scenario: 解包结果引用未授权材料

- **WHEN** 内层 JSON 可解析但包含未筛选候选、历史句柄、跨 Workspace 对象或错误 Entry/Source 关系
- **THEN** 既有输出、权限与来源校验拒绝结果，兼容层不替换或授权引用

### Requirement: 格式重试和收尾必须保留已通过检查的内容

普通求解输出在格式或引用校验重试前，系统 MUST 保存其中已通过自身内容边界的文本块及其模型通用知识标注，并 MUST 将未通过的结构化块、未筛选候选和未经授权引用隔离。后续软阈值或 finalizer 失败时，系统 MUST 使用或保留该受限文本，不得由更弱的失败说明覆盖；未经完整校验的原始输出仍不得整体接受。

#### Scenario: 通用解释因待筛选候选触发重试

- **WHEN** 普通求解已生成带通用知识标注的完整概念解释，但同轮未筛选候选导致输出校验要求重试且下一请求触发软阈值
- **THEN** 无工具 finalizer 收到该已检查文本并保持通用知识边界，最终用户不只看到“知识库无法回答”

#### Scenario: 原输出混有未授权资料块

- **WHEN** 同一输出包含可保留通用文本以及引用未筛选候选的列表、Entry 或 Evidence 块
- **THEN** 系统只保存文本候选，丢弃未授权资料块并继续执行完整最终输出校验

### Requirement: 收尾转换和模型失败审计必须准确

`finalize_transition` 表示求解请求因程序停止点未派发，生产适配器 MUST 将其记录为 `not_dispatched`，保留 `input_soft_limit` 等停止原因、输入投影和零耗时，并 MUST NOT 标记为 fallback 或 `model_call_failed`。已派发后发生的 Provider、超时或协议失败 MUST 继续记录真实失败。

#### Scenario: 软阈值转换未派发

- **WHEN** 9290 输入投影触发 `finalize_transition` 且该求解请求没有发送给 Provider
- **THEN** 审计 outcome 为 `not_dispatched`、`is_fallback=false`，并保留 `finalize_reason=input_soft_limit`

#### Scenario: Provider 调用真实失败

- **WHEN** 文本请求已经派发且 Provider 返回错误或超时
- **THEN** 审计 outcome 仍为 `model_call_failed` 并保留原错误，不被归类成未派发

### Requirement: 正式 Web 必须展示真实 dialogue-loop 阶段

生产适配器 MUST 将统一循环已有 activity callback 的去重阶段通过正式 Run API 暴露给 Grove Web。Web MUST 使用真实阶段显示轻量、可访问的“组织回答中”“查询知识库中”“读取记录中”“核验来源中”或“整理回答中”，不得用定时器推测阶段，不得恢复诊断侧栏。完成、部分完成、失败或取消后 MUST 停止动效；刷新、切换会话及 continuation MUST 只显示当前活动 Run 的当前阶段，并遵守减少动画偏好。

#### Scenario: 正式 Run 推进真实阶段

- **WHEN** 统一循环依次发布 organizing、querying、reading_entries、reading_sources 与 finalizing
- **THEN** 正式 API 和 Web 依次呈现对应用户文案，阶段变化不改写 Worker 恢复用 `current_step`

#### Scenario: 终态和会话切换清理阶段

- **WHEN** Run 进入 completed、partial、failed 或 cancelled，或用户切换到另一会话
- **THEN** 页面停止该 Run 动效且不显示上一会话或上一 Run 的阶段

#### Scenario: 减少动画偏好

- **WHEN** 用户系统启用 `prefers-reduced-motion: reduce`
- **THEN** 阶段文案和可访问状态播报仍可用，旋转或脉冲动效停止
