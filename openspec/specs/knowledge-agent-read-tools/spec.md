# knowledge-agent-read-tools Specification

## Purpose
受服务端可信范围约束的只读知识工具：搜索正式知识、读取 Entry 与核验 Source/Attachment 证据；最终引用只能指向本 Run 的可引用 Evidence 句柄。

## Requirements
### Requirement: 工具使用服务端可信范围
所有知识 Agent 只读工具 MUST 从 Run 读取可信的用户、Workspace 和可选项目范围，MUST NOT 接受模型传入的 Workspace 或项目作为授权依据；每次对象读取 MUST 再次验证范围。

#### Scenario: 模型猜测其他 Workspace 标识
- **WHEN** 模型在工具参数中构造或猜测其他 Workspace 的对象标识
- **THEN** 工具不返回该对象且记录被拒绝的调用结果

#### Scenario: 项目范围读取其他项目对象
- **WHEN** 项目范围 Run 请求读取同 Workspace 的其他项目 Entry
- **THEN** 工具拒绝读取且不泄露 Entry 内容

### Requirement: 搜索正式知识工具
系统 MUST 提供搜索正式知识工具，在 Run 的 Workspace 或项目范围内复用混合召回，并且只返回已确认的正式 Entry；Workspace 范围结果 MUST 带项目归属，目录路径只能作为内部排序与结果定位信息。

#### Scenario: Workspace 范围搜索
- **WHEN** Workspace 范围 Run 搜索一个问题
- **THEN** 工具可返回当前 Workspace 多个项目中的相关正式 Entry，并为每项提供项目归属

#### Scenario: 项目范围搜索
- **WHEN** 项目范围 Run 搜索一个问题
- **THEN** 工具只返回该项目中的相关正式 Entry

#### Scenario: 候选内容不进入搜索结果
- **WHEN** 范围内存在尚未确认的 Extraction 或其他 AI 候选
- **THEN** 搜索工具不将其作为知识回答依据返回

### Requirement: Entry 读取受已发现集合约束
系统 MUST 只允许读取本轮搜索结果或用户在本轮显式引用、且仍属于 Run 范围的 Entry；Entry 读取 MUST 返回完整正式内容以及项目、目录和来源关系，不得因模型提供有效 UUID 而绕过发现过程。

#### Scenario: 读取搜索发现的 Entry
- **WHEN** 模型请求批量读取本轮搜索返回且属于当前范围的 Entry
- **THEN** 工具返回这些 Entry 的完整正式内容与归属信息

#### Scenario: 读取未发现 Entry
- **WHEN** 模型请求读取未被本轮发现或用户引用的 Entry
- **THEN** 工具拒绝读取并记录授权失败

#### Scenario: Entry 在读取前移出范围
- **WHEN** 已发现 Entry 在工具读取前不再属于 Run 固化范围
- **THEN** 工具不返回其内容并记录对象已不可用

### Requirement: Source 证据读取与原文核验
系统 MUST 仅针对已发现 Entry 的真实 Source 关联读取 Attachment 文本或 OCR 文本，并将候选片段核验为原始内容中的精确子串；无法核验、无权限或关联无效的片段 MUST NOT 标记为可引用。

#### Scenario: 核验真实原文片段
- **WHEN** Entry 关联 Source 的 Attachment 内容中能定位候选片段
- **THEN** 系统保存原始内容中的精确子串及 Entry/Source/Attachment 关系为可引用 Evidence

#### Scenario: OCR 差异可归一化定位
- **WHEN** 候选片段存在可接受的空白或 OCR 差异且归一化后能定位
- **THEN** 系统仍保存原始 Attachment 中实际存在的精确子串而非模型改写文本

#### Scenario: 原文无法核验
- **WHEN** Source 无可读 Attachment 内容或候选片段无法定位
- **THEN** 工具记录证据不可用且不生成可引用 Evidence

#### Scenario: Source 不属于 Entry
- **WHEN** 模型请求读取与已发现 Entry 无真实关联的 Source
- **THEN** 工具拒绝读取且不返回 Source 或 Attachment 内容

### Requirement: Run Evidence 形成稳定引用句柄
系统 MUST 为本 Run 实际读取且核验通过的证据创建不可由模型伪造的 Evidence 句柄，并保存 Entry、Project、Source、Attachment、原文、定位信息与来源内容指纹快照；最终回答只能引用当前 Run 的可引用句柄。

#### Scenario: 模型选择有效 Evidence
- **WHEN** 回答模型返回当前 Run 的可引用 Evidence 句柄
- **THEN** 服务端将该句柄解析为结构化引用并返回核验后的原文

#### Scenario: 模型构造无效句柄或 quote
- **WHEN** 回答模型返回其他 Run 的句柄、未知句柄或自行生成的 quote
- **THEN** 服务端丢弃该引用且不使用模型 quote 替代真实原文

#### Scenario: 来源后来发生变化
- **WHEN** 历史回答对应的 Attachment 内容在回答完成后变化或不可用
- **THEN** 历史 Evidence 保留生成时快照与内容指纹，并可被识别为来源已变化或不可用

### Requirement: 工具调用可审计且内容最小化
系统 MUST 按执行顺序记录每次工具调用的工具名、脱敏参数摘要、结果摘要、状态、错误、耗时及相关模型降级信息；记录 MUST NOT 无限制复制整份 Entry、Attachment 或敏感原始 prompt。

#### Scenario: 工具正常完成
- **WHEN** 工具成功返回搜索、Entry 或 Evidence 结果
- **THEN** 系统记录调用顺序、结果数量、对象句柄和耗时

#### Scenario: 工具部分失败
- **WHEN** 批量读取中部分对象越权、失效或无法核验
- **THEN** 系统记录部分失败详情并仅把成功对象传给后续步骤
