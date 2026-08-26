## MODIFIED Requirements

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

## ADDED Requirements

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
