## ADDED Requirements

### Requirement: embedding 配置与密钥复用
系统 MUST 为每个 Workspace 维护 embedding 配置（Provider、模型名、是否已配置、是否可用），并 MUST 复用豆包视觉密钥作为 embedding 密钥，不得要求用户为 embedding 重复填写密钥；未配置豆包密钥时 MUST 标记 embedding 未配置。

#### Scenario: 查看 embedding 配置
- **WHEN** 用户打开模型设置页
- **THEN** 系统返回脱敏的 embedding Provider、模型名、是否已配置与可用状态，不返回任何密钥

#### Scenario: embedding 复用豆包密钥
- **WHEN** 当前 Workspace 已配置豆包视觉密钥
- **THEN** embedding 使用同一把密钥即可编码，用户无需再次填写密钥

#### Scenario: 未配置豆包密钥
- **WHEN** 当前 Workspace 未配置豆包视觉密钥
- **THEN** embedding 状态显示未配置，语义功能退回确定性链路

### Requirement: 纯文本向量编码
系统 MUST 通过豆包多模态向量化端点对纯文本编码为稠密向量；相同模型 MUST 输出固定维度的向量；编码调用 MUST 返回 provider / model / is_fallback / error，未配置密钥或调用失败时 MUST 返回明确降级信息，不得静默中断。

#### Scenario: 纯文本编码成功
- **WHEN** 业务代码对一段已确认 Entry 文本请求向量
- **THEN** 系统调用方舟多模态向量化端点并返回固定维度稠密向量

#### Scenario: 编码失败明确降级
- **WHEN** 密钥缺失或编码接口调用失败
- **THEN** 系统返回降级标记与错误信息，调用方退回确定性召回

### Requirement: Entry 向量持久化与 Workspace 隔离
系统 MUST 为已确认 Entry 持久化稠密向量，并按 Workspace 与 Project 隔离存储；检索 MUST 只使用当前 Workspace 内、所选范围内的 Entry 向量，不得跨 Workspace 或跨项目使用向量。

#### Scenario: 向量落库
- **WHEN** 一条 Entry 完成向量编码
- **THEN** 向量与该 Entry 的 Workspace、Project、模型、维度一起持久化

#### Scenario: 跨 Workspace 不可见
- **WHEN** 用户在当前 Workspace 发起语义检索
- **THEN** 向量召回只覆盖当前 Workspace 的 Entry，不返回其他 Workspace 的任何结果

### Requirement: 向量异步重建
系统 MUST 在 Entry 创建、编辑、删除、版本恢复或修订草稿应用后，异步重建或失效该 Entry 的向量；重建失败 MUST 记录错误并允许重试；向量未就绪的 Entry MUST 不进入 embedding 召回（仍可进入确定性召回）。

#### Scenario: 变更触发重建
- **WHEN** 一条已确认 Entry 的内容被修改
- **THEN** 该 Entry 的向量被标记待重建，并由后台任务重新编码覆盖写回

#### Scenario: 重建失败重试
- **WHEN** 向量重建调用失败
- **THEN** 系统记录错误并保留待重建状态，后续重试直到成功或明确失败

#### Scenario: 未就绪跳过向量召回
- **WHEN** 一条 Entry 的向量尚未编码完成
- **THEN** embedding 召回跳过该 Entry，确定性召回仍可命中

### Requirement: 混合召回
系统 MUST 将确定性召回（关键词与字符重叠）与 embedding 向量召回合并去重后生成候选集，供语义重排或关系判断使用；embedding 未配置、失败或无可用向量时 MUST 降级为仅确定性召回并明确标记。

#### Scenario: 混合召回合并
- **WHEN** 用户发起语义搜索且 embedding 可用
- **THEN** 候选集为确定性召回与 embedding 召回去重后的并集

#### Scenario: embedding 降级
- **WHEN** 当前 Workspace 未配置 embedding 或编码失败
- **THEN** 候选集仅来自确定性召回，系统记录降级标记，不中断流程

### Requirement: 相似度阈值规则判定
系统 MUST 使用候选与其 top-1 相似 Entry 的向量相似度阈值规则接管部分关系判定：相似度不低于 `T_high` 时 MUST 直接判定 `duplicate` 并指向该 Entry；相似度不高于 `T_low` 时 MUST 直接判定 `new`；相似度处于 `T_low` 与 `T_high` 之间时 MUST 交由文本模型判定 `duplicate` / `supplement` / `conflict`；`supplement` 与 `conflict` MUST 始终由文本模型判定。规则直判结果 MUST 是候选建议，最终动作由用户确认；目标 Entry 非法时 MUST 降级为 `new`。

#### Scenario: 高相似直判重复
- **WHEN** 候选与 top-1 相似 Entry 的向量相似度不低于 `T_high`
- **THEN** 系统直判 `duplicate` 并指向该 Entry，不调用文本模型

#### Scenario: 低相似直判新建
- **WHEN** 候选与 top-1 相似 Entry 的向量相似度不高于 `T_low`
- **THEN** 系统直判 `new`，不调用文本模型

#### Scenario: 中间区间交 LLM
- **WHEN** 候选与 top-1 相似 Entry 的相似度处于 `T_low` 与 `T_high` 之间
- **THEN** 系统交由文本模型判定 `duplicate` / `supplement` / `conflict`

#### Scenario: 目标 Entry 非法降级新建
- **WHEN** 规则直判 `duplicate` 但目标 Entry 不存在或不属于当前项目
- **THEN** 系统将关系状态降级为 `new`

### Requirement: embedding 连接测试
系统 MUST 提供 embedding 连接测试，用最小纯文本编码校验密钥与模型可用；成功 MUST 更新 `embedding_available`，失败 MUST 返回明确错误且不覆盖已有配置。

#### Scenario: 测试 embedding 连接成功
- **WHEN** 用户对 embedding 配置执行测试连接
- **THEN** 系统调用一次最小文本编码并标记 embedding 可用

#### Scenario: 测试失败不覆盖配置
- **WHEN** embedding 连接测试失败
- **THEN** 系统返回明确错误，保留已有配置与密钥，不静默清空

### Requirement: embedding 可观测性
系统 MUST 在 embedding 编码与重建路径记录 provider / model / is_fallback / error；调用失败 MUST 日志告警，禁止静默降级。

#### Scenario: 编码来源可识别
- **WHEN** embedding 编码成功
- **THEN** 调用方与日志可识别 provider、模型名与成功状态

#### Scenario: 降级告警
- **WHEN** embedding 编码失败或未配置
- **THEN** 系统记录降级原因并告警，调用方按确定性召回继续
