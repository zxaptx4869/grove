## MODIFIED Requirements

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

#### Scenario: 读取本轮搜索发现的 Entry
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

