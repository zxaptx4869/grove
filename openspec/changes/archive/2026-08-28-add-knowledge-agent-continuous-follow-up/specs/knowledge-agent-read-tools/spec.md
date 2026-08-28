## MODIFIED Requirements

### Requirement: Entry 读取受已发现集合约束
系统 MUST 只允许读取本轮搜索结果、当前 Run 固化工作集中的复验有效种子，或用户在本轮显式引用且仍属于 Run 范围的 Entry；Entry 读取 MUST 返回完整正式内容以及项目、目录和来源关系，不得因模型提供有效 UUID 而绕过发现过程。

#### Scenario: 读取搜索发现的 Entry
- **WHEN** 模型请求批量读取本轮搜索返回且属于当前范围的 Entry
- **THEN** 工具返回这些 Entry 的完整正式内容与归属信息

#### Scenario: 读取工作集种子 Entry
- **WHEN** `continue` Run 请求读取输入工作集中经服务端复验仍属于当前范围的正式 Entry
- **THEN** 工具将这些 Entry 视为已发现对象并返回当前正式内容

#### Scenario: 读取未发现 Entry
- **WHEN** 模型请求读取未被本轮搜索、工作集复验或用户引用发现的 Entry
- **THEN** 工具拒绝读取并记录授权失败

#### Scenario: Entry 在读取前移出范围
- **WHEN** 已发现或工作集中的 Entry 在工具读取前不再属于 Run 固化范围
- **THEN** 工具不返回其内容并记录对象已不可用

### Requirement: Run Evidence 形成稳定引用句柄
系统 MUST 为本 Run 实际重新读取且核验通过的证据创建不可由模型伪造的 Evidence 句柄，并保存 Entry、Project、Source、Attachment、原文、定位信息与来源内容指纹快照；最终回答只能引用当前 Run 的可引用句柄，历史工作集或历史 Run Evidence 不能直接替代本轮核验。

#### Scenario: 工作集 Entry 重新生成 Evidence
- **WHEN** 继续追问使用工作集 Entry 支持本轮结论
- **THEN** 系统重新读取当前 Source/Attachment 并为当前 Run 创建新的可引用 Evidence

#### Scenario: 模型选择有效 Evidence
- **WHEN** 回答模型返回当前 Run 的可引用 Evidence 句柄
- **THEN** 服务端将该句柄解析为结构化引用并返回核验后的原文

#### Scenario: 模型构造无效句柄或 quote
- **WHEN** 回答模型返回历史 Run、范围外、未知句柄或自行生成的 quote
- **THEN** 服务端丢弃该引用且不使用模型 quote 替代真实原文

#### Scenario: 来源后来发生变化
- **WHEN** 工作集 Entry 对应的 Attachment 内容自上一轮后变化或不可用
- **THEN** 当前 Run 按新内容重新核验或拒绝引用，历史 Evidence 保留旧快照但不进入本轮回答

## ADDED Requirements

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
