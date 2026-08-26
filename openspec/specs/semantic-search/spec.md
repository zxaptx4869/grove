# semantic-search Specification

## Purpose
提供语义检索：确定性候选召回与文本模型语义重排，未配置密钥时明确降级并附带相关理由返回结果，供问答与相似推荐复用。
## Requirements
### Requirement: 语义检索对象与范围
系统 MUST 只检索当前 Workspace 内的已确认 Entry；检索范围 MUST 支持指定项目内或当前 Workspace 全局；语义检索 MUST NOT 改变任何 Entry 的项目归属。

#### Scenario: 只检索已确认 Entry
- **WHEN** 用户发起语义搜索
- **THEN** 检索对象仅为当前 Workspace 内的正式 Entry，不包含候选或来源

#### Scenario: 项目内与全局两种范围
- **WHEN** 用户选择项目内或全局语义搜索
- **THEN** 分别只返回该项目内或当前 Workspace 全部项目的已确认 Entry

### Requirement: 语义重排与相关理由
系统 MUST 调用文本模型对候选 Entry 按与查询的语义相关度重排，返回最多 10 条结果，并为每条返回一句话相关理由；未配置文本模型密钥时 MUST 明确降级为确定性召回结果并标记 fallback，不得静默调用外部服务。

#### Scenario: 语义重排返回排序结果
- **WHEN** 候选集非空且当前 Workspace 配置了文本模型
- **THEN** 返回按语义相关度排序的最多 10 条 Entry，每条带相关理由

#### Scenario: 未配置密钥时明确降级
- **WHEN** 当前 Workspace 未配置文本模型密钥
- **THEN** 按召回分数降序返回确定性召回结果并标记为降级（fallback），不调用外部服务

### Requirement: 项目内语义搜索
系统 MUST 支持在指定项目内语义搜索；无匹配时 MUST 返回空结果。

#### Scenario: 项目内语义搜索
- **WHEN** 用户在某个项目内输入查询并语义搜索
- **THEN** 只返回该项目内语义相关的已确认 Entry

#### Scenario: 无匹配返回空
- **WHEN** 项目内没有语义相关的 Entry
- **THEN** 返回空结果

### Requirement: 全局语义搜索
系统 MUST 支持跨当前 Workspace 全部项目语义搜索；结果 MUST 标注每条 Entry 所属项目，且 MUST NOT 改变 Entry 归属。

#### Scenario: 跨项目命中并标注项目
- **WHEN** 用户从全局语义搜索输入查询
- **THEN** 返回当前 Workspace 内所有项目命中的 Entry，并标注各自项目名

#### Scenario: 不改变归属
- **WHEN** 用户查看全局语义搜索结果
- **THEN** Entry 的项目归属保持不变

### Requirement: 越权项目不可见
用户请求语义搜索不属于当前 Workspace 的项目 MUST 失败（404），不暴露其他 Workspace 数据。

#### Scenario: 越权项目 404
- **WHEN** 用户请求语义搜索不属于当前 Workspace 的项目
- **THEN** 请求失败（404），不返回任何数据

### Requirement: 混合候选召回
系统 MUST 在语义重排前，基于查询与 Entry 标题、核心内容、目录节点名称及来源标题的关键词与字符重叠做确定性召回，并合并当前 Workspace 与所选范围内已确认 Entry 的 embedding 向量召回，形成候选集；候选集 MUST 限定在当前 Workspace 与所选范围内；embedding 未配置、调用失败或无可用向量时 MUST 降级为仅确定性召回并明确标记，不得静默中断。

#### Scenario: 生成候选集
- **WHEN** 用户输入自然语言查询且 embedding 可用
- **THEN** 系统返回确定性召回与 embedding 召回去重合并后的候选 Entry 集合，供语义重排使用

#### Scenario: embedding 降级为确定性召回
- **WHEN** 当前 Workspace 未配置 embedding 或编码失败
- **THEN** 系统返回确定性召回候选集并明确标记降级，不调用外部服务

#### Scenario: 候选集限定范围
- **WHEN** 用户在项目内或全局发起语义搜索
- **THEN** 混合候选集只包含该项目内或当前 Workspace 全部项目的已确认 Entry

