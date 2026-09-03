# knowledge-agent-read-tools Specification

## Purpose
受服务端可信范围约束的只读知识工具：搜索正式知识、读取 Entry 与核验 Source/Attachment 证据；最终引用只能指向本 Run 的可引用 Evidence 句柄。
## Requirements
### Requirement: 工具使用服务端可信范围
所有知识 Agent 只读工具 MUST 从 Run 读取可信的用户、Workspace 和可选项目范围，MUST NOT 接受模式路由器、调查控制器或回答模型传入的 Workspace 或项目作为授权依据；每次对象读取与每轮查询 MUST 再次验证范围，模型提出的文本查询 MUST NOT 改变范围。

#### Scenario: 模型猜测其他 Workspace 标识
- **WHEN** 任一模型在工具参数中构造或猜测其他 Workspace 的对象标识
- **THEN** 工具不返回该对象且记录被拒绝的调用结果

#### Scenario: 项目范围读取其他项目对象
- **WHEN** 项目范围 Run 请求读取同 Workspace 的其他项目 Entry
- **THEN** 工具拒绝读取且不泄露 Entry 内容

#### Scenario: 调查查询试图指定范围
- **WHEN** 控制器在查询文本之外输出 Workspace、项目或目录范围参数
- **THEN** 应用忽略或拒绝该参数并继续只使用 Run 固化范围

### Requirement: 搜索正式知识工具
系统 MUST 提供搜索正式知识工具，在 Run 的 Workspace 或项目范围内复用混合召回，并且只返回已确认的正式 Entry；Workspace 范围结果 MUST 带项目归属，目录路径只能作为内部排序与结果定位信息；调查模式 MUST 按轮次记录每个实际查询的结果归属并在当前 Run 内全局去重。

#### Scenario: Workspace 范围搜索
- **WHEN** Workspace 范围 Run 搜索一个问题
- **THEN** 工具可返回当前 Workspace 多个项目中的相关正式 Entry，并为每项提供项目归属

#### Scenario: 项目范围搜索
- **WHEN** 项目范围 Run 搜索一个问题
- **THEN** 工具只返回该项目中的相关正式 Entry

#### Scenario: 候选内容不进入搜索结果
- **WHEN** 范围内存在尚未确认的 Extraction 或其他 AI 候选
- **THEN** 搜索工具不将其作为知识回答依据返回

#### Scenario: 多轮查询结果去重
- **WHEN** 调查的多个查询命中同一正式 Entry
- **THEN** 工具保留必要的查询命中审计，但该 Entry 只计入一次不同对象预算

### Requirement: Entry 读取受已发现集合约束
系统 MUST 只允许读取本 Run 任一已提交搜索结果、固化工作集中的复验有效种子，或用户在本 Run 显式引用且仍属于 Run 范围的 Entry；调查中已发现集合 MUST 跨轮次累积并在每次读取前复验。Entry 读取 MUST 返回完整正式内容以及项目、目录和来源关系，不得因模型提供有效 UUID 而绕过发现过程。

#### Scenario: 读取搜索发现的 Entry
- **WHEN** 模型请求批量读取当前轮搜索返回且属于当前范围的 Entry
- **THEN** 工具返回这些 Entry 的完整正式内容与归属信息

#### Scenario: 读取先前轮次发现的 Entry
- **WHEN** 后续调查轮请求读取本 Run 先前已提交轮次发现且仍属于范围的 Entry
- **THEN** 工具将这些 Entry 视为已发现对象并返回当前正式内容

#### Scenario: 读取工作集种子 Entry
- **WHEN** `continue` Run 请求读取输入工作集中经服务端复验仍属于当前范围的正式 Entry
- **THEN** 工具将这些 Entry 视为已发现对象并返回当前正式内容

#### Scenario: 读取未发现 Entry
- **WHEN** 模型请求读取未被本 Run 搜索、工作集复验或用户引用发现的 Entry
- **THEN** 工具拒绝读取并记录授权失败

#### Scenario: Entry 在读取前移出范围
- **WHEN** 已发现或工作集中的 Entry 在工具读取前不再属于 Run 固化范围
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
系统 MUST 为本 Run 任一轮实际重新读取且核验通过的证据创建不可由模型伪造的 Evidence 句柄，并保存 Entry、Project、Source、Attachment、原文、定位信息、来源内容指纹快照与轮次归属；最终回答只能引用当前 Run 的可引用句柄，历史工作集或历史 Run Evidence 不能直接替代本轮核验，同一证据在多轮命中 MUST 幂等复用而不重复计数。

#### Scenario: 工作集 Entry 重新生成 Evidence
- **WHEN** quick 或调查追问使用工作集 Entry 支持本轮结论
- **THEN** 系统重新读取当前 Source/Attachment 并为当前 Run 创建新的可引用 Evidence

#### Scenario: 后续轮次再次命中相同证据
- **WHEN** 调查后续轮次再次读取同一 Entry/Source/Attachment 的同一核验依据
- **THEN** 系统复用当前 Run 已有 Evidence 身份并保留必要轮次归属，不重复消耗不同 Evidence 预算

#### Scenario: 模型选择有效 Evidence
- **WHEN** 回答模型返回当前 Run 的可引用 Evidence 句柄
- **THEN** 服务端将该句柄解析为结构化引用并返回核验后的原文

#### Scenario: 模型构造无效句柄或 quote
- **WHEN** 模型返回历史 Run、范围外、未知句柄或自行生成的 quote
- **THEN** 服务端丢弃该引用且不使用模型 quote 替代真实原文

#### Scenario: 来源后来发生变化
- **WHEN** 工作集或先前轮次 Entry 对应的 Attachment 内容发生变化或不可用
- **THEN** 当前 Run 按最新内容重新核验或拒绝引用，历史 Evidence 快照不进入当前结论

### Requirement: 工具调用可审计且内容最小化
系统 MUST 按执行顺序记录每次工具调用的工具名、脱敏参数摘要、结果摘要、状态、错误、耗时、相关模型降级信息及可选轮次/查询归属；记录 MUST NOT 无限制复制整份 Entry、Attachment、调查账本或敏感原始 prompt。

#### Scenario: 工具正常完成
- **WHEN** 工具成功返回搜索、Entry 或 Evidence 结果
- **THEN** 系统记录调用顺序、轮次/查询归属、结果数量、对象句柄和耗时

#### Scenario: 工具部分失败
- **WHEN** 批量读取中部分对象越权、失效或无法核验
- **THEN** 系统记录受影响轮次与部分失败详情并仅把成功对象传给后续步骤

#### Scenario: 大体积原文被读取
- **WHEN** Evidence 工具读取长 Attachment
- **THEN** 审计只保存长度受限摘要、对象句柄与定位，不复制整份原文

### Requirement: 工作集种子与新召回统一合并重排
系统 MUST 在 `continue` Run 中重新校验输入工作集 Entry，并将有效种子与独立查询的新混合召回结果去重、统一重排和按回答上下文上限截断；工作集 MUST NOT 阻止系统发现当前追问所需的新 Entry。

#### Scenario: 旧主题与新知识合并
- **WHEN** 追问既涉及上一轮 Entry 又需要范围内其他 Entry
- **THEN** 工具候选包含有效工作集种子和新召回项，并按独立查询统一排序

#### Scenario: 工作集种子已删除
- **WHEN** 输入工作集引用的 Entry 已删除、越权或移出项目范围
- **THEN** 系统排除该种子、记录不可用并继续新检索

#### Scenario: 合并后超过上下文上限
- **WHEN** 去重后的工作集种子与新召回多于回答上限
- **THEN** 系统按统一重排结果确定性截断，不因种子身份无条件保留低相关项

### Requirement: Knowledge Agent 只读工具统一经受控执行入口调用
系统 MUST 让新增结构化查询工具经应用控制的白名单执行入口调用，并使既有知识搜索、Entry 读取与 Evidence 读取能够使用相同的工具版本、可信上下文、状态和审计协议；统一入口 MUST NOT 改变既有已发现集合、Evidence 核验或最终 Citation 边界，也 MUST NOT 接受模型提供的授权范围。

#### Scenario: 结构化查询使用 Run 可信上下文
- **WHEN** Worker 调用 `query_entries` 或 `aggregate_entries`
- **THEN** 执行入口从 Run 注入 owner、Workspace 和可选项目范围，工具参数中不存在可由模型覆盖的范围字段

#### Scenario: 既有 Evidence 工具接入统一状态
- **WHEN** 既有 read_evidence 在批量读取中出现部分不可用对象
- **THEN** 调用继续遵守发现集合与原文核验规则，并使用统一 partial 状态和有界审计摘要，不因适配执行入口放宽读取权限

#### Scenario: 模型请求未注册工具
- **WHEN** 计划或后续控制器输出不在服务端白名单中的工具名
- **THEN** 执行入口记录 denied 并拒绝调用，不通过动态导入、反射或名称猜测执行代码

