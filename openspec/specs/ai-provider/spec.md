# ai-provider Specification

## Purpose
管理每个 Workspace 的 AI Provider 配置与密钥，提供文本/视觉模型获取与连接测试，未配置密钥时回退离线确定性模型。
## Requirements
### Requirement: AI Provider 抽象接口
后端 MUST 使用 PydanticAI 的 provider/client 体系提供模型访问能力；文本模型与视觉模型 MUST 通过统一服务层获取，业务代码 MUST NOT 直接持有第三方客户端；结构化输出 MUST 使用 Pydantic 模型定义。

#### Scenario: 接口可被实现与调用
- **WHEN** 服务层返回一个已配置的模型
- **THEN** 该模型可被 PydanticAI Agent 调用并返回结构化输出

#### Scenario: 通过服务层获取文本模型
- **WHEN** 业务代码需要文本模型
- **THEN** 通过统一服务层返回一个可调用的 PydanticAI 模型，业务代码不接触第三方 provider 细节

#### Scenario: 视觉模型与文本模型解耦
- **WHEN** 业务代码需要视觉/OCR 能力
- **THEN** 通过独立的视觉模型服务获取，不与文本模型混用同一实例

### Requirement: Demo Provider 确定性实现
系统 MUST 提供离线确定性测试模型，用于未配置密钥、测试或断网场景跑通结构化输出流程；离线模型 MUST NOT 调用任何外部 API。

#### Scenario: 相同输入产生相同输出
- **WHEN** 以相同输入连续两次调用离线测试模型
- **THEN** 两次返回的结构化候选内容完全一致

#### Scenario: 未配置密钥时使用离线模型
- **WHEN** 当前 Workspace 未配置真实模型密钥
- **THEN** 系统回退到离线确定性测试模型，不发起外部网络请求

### Requirement: Provider 工厂可切换
系统 MUST 根据当前 Workspace 的模型配置返回对应的文本模型与视觉模型；未配置时 MUST 回退到离线模型；配置了不支持或缺失密钥的 Provider 时 MUST 明确报错，不得静默调用外部服务。

#### Scenario: 默认使用 Demo Provider
- **WHEN** 当前 Workspace 未配置任何真实模型密钥
- **THEN** 模型服务返回离线确定性模型，不调用外部服务

#### Scenario: 配置 DeepSeek 文本 Provider
- **WHEN** 当前 Workspace 配置了 DeepSeek 文本密钥
- **THEN** 文本模型使用 DeepSeek Provider 并读取该密钥

#### Scenario: 配置豆包视觉 Provider
- **WHEN** 当前 Workspace 配置了豆包视觉密钥
- **THEN** 视觉模型使用豆包视觉 Provider 并读取该密钥

#### Scenario: 未配置密钥明确提示
- **WHEN** 业务代码请求真实 Provider 但当前 Workspace 未配置对应密钥
- **THEN** 行为明确标记为未配置或回退到离线模型，不静默调用外部服务

#### Scenario: 未接入供应商明确提示
- **WHEN** 配置了当前不支持的 Provider 标识
- **THEN** 行为明确标记为未接入，不得静默调用外部服务

### Requirement: AI 输出候选铁律
AI 生成的任何抽取、候选或理解 MUST 标记为候选，不得直接写入或覆盖正式 Entry 或正式目录；候选标记 MUST 在结构化输出与持久化层可被消费方识别。

#### Scenario: 候选标记可被消费方识别
- **WHEN** 消费方读取 Agent 输出
- **THEN** 能通过明确的候选标记或落库位置判断该结果为候选，且仓库守则禁止其直接成为正式记录

### Requirement: 模型密钥配置
系统 MUST 允许用户为当前 Workspace 配置自己的文本模型、视觉模型与 embedding 模型；产品本身 MUST NOT 提供或内置模型密钥；密钥 MUST 通过系统钥匙串或等价加密存储，数据库 MUST NOT 保存明文密钥；接口 MUST 只返回脱敏后的配置信息；embedding 复用豆包视觉密钥时 MUST NOT 要求用户重复填写密钥。

#### Scenario: 配置文本密钥
- **WHEN** 用户在模型设置中填写 DeepSeek 文本密钥并保存
- **THEN** 密钥存入安全存储，数据库只保存 Provider、模型与密钥尾号等脱敏信息

#### Scenario: 配置视觉密钥
- **WHEN** 用户在模型设置中填写豆包视觉密钥并保存
- **THEN** 密钥存入安全存储，数据库只保存脱敏信息

#### Scenario: embedding 复用视觉密钥
- **WHEN** 当前 Workspace 已配置豆包视觉密钥
- **THEN** embedding 复用该密钥，用户无需为 embedding 单独填写密钥

#### Scenario: 查询只返回脱敏信息
- **WHEN** 用户查看模型设置
- **THEN** 返回各模型的 Provider、模型名、是否已配置与密钥尾号，绝不返回完整密钥

#### Scenario: Workspace 隔离
- **WHEN** 不同 Workspace 各自配置密钥
- **THEN** 每个 Workspace 只能读取自己的密钥与配置，不能跨 Workspace 访问

### Requirement: 模型连接校验
系统 MUST 提供测试连接能力，校验当前 Workspace 配置的文本、视觉与 embedding 模型是否可用；成功 MUST 更新对应可用状态，失败 MUST 返回明确错误且不覆盖已有配置。

#### Scenario: 测试文本连接成功
- **WHEN** 用户用有效文本密钥执行测试连接
- **THEN** 系统调用一次最小文本补全并标记文本配置可用

#### Scenario: 测试视觉连接成功
- **WHEN** 用户用有效视觉密钥执行测试连接
- **THEN** 系统调用一次最小视觉理解并标记视觉配置可用

#### Scenario: 测试 embedding 连接成功
- **WHEN** 用户对 embedding 配置执行测试连接
- **THEN** 系统调用一次最小纯文本编码并标记 embedding 配置可用

#### Scenario: 测试失败不覆盖配置
- **WHEN** 任一模型连接测试失败
- **THEN** 返回明确错误，保留已有配置与密钥，不静默清空

### Requirement: Embedding 模型获取
系统 MUST 通过统一服务层提供 embedding 编码能力，业务代码 MUST NOT 直接持有第三方客户端；未配置豆包密钥时 MUST 返回离线确定性 embedding，不访问外部网络；embedding 调用 MUST 记录 provider / model / is_fallback / error，失败 MUST 明确标记，不得静默降级。

#### Scenario: 通过服务层获取 embedding
- **WHEN** 业务代码需要编码一段文本
- **THEN** 通过统一服务层获得稠密向量，业务代码不接触豆包请求细节

#### Scenario: 未配置密钥离线编码
- **WHEN** 当前 Workspace 未配置豆包密钥
- **THEN** 服务层返回离线确定性 embedding 并标记降级，不发起外部网络请求

#### Scenario: 调用失败明确标记
- **WHEN** embedding 编码调用失败
- **THEN** 返回降级标记与错误信息，调用方不得将其当作成功结果

