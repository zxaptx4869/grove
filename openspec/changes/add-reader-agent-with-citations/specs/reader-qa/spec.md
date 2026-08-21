# reader-qa Specification

## Purpose
AI 阅读问答：在节点或项目范围内，基于已确认 Entry 提供带引用的回答，知识不足与冲突可见。

## ADDED Requirements

### Requirement: 问答范围与 Workspace 隔离
系统 MUST 支持节点阅读（当前节点及其子树）与项目阅读（整个项目）两种问答范围；问答 MUST 只读取当前 Workspace 内已确认的正式 Entry；越权项目或节点 MUST 失败（404），不暴露其他 Workspace 数据。

#### Scenario: 节点阅读
- **WHEN** 用户对某个目录节点发起问答
- **THEN** 回答只基于该节点及其全部后代节点的已确认 Entry

#### Scenario: 项目阅读
- **WHEN** 用户对某个项目发起问答
- **THEN** 回答基于该项目全部已确认 Entry

#### Scenario: 越权项目 404
- **WHEN** 用户请求不属于当前 Workspace 的项目问答
- **THEN** 请求失败（404），不返回任何数据

### Requirement: 证据召回复用语义检索
系统 MUST 复用语义检索的确定性召回与文本模型语义重排，按用户问题召回最多 15 条已确认 Entry 作为问答上下文；未配置文本模型密钥或模型调用失败时 MUST 降级为确定性召回结果并标记，不得静默调用外部服务。

#### Scenario: 按问题召回上下文
- **WHEN** 用户输入问题并发起问答
- **THEN** 系统返回与问题语义相关的已确认 Entry 作为回答上下文

#### Scenario: 模型失败降级
- **WHEN** 文本模型不可用（未配置密钥或调用失败）
- **THEN** 使用确定性召回结果作为上下文并标记降级，不中断问答

### Requirement: 带引用回答
系统 MUST 返回结构化回答，包含答案文本与引用列表；引用 MUST 包含 `entry_id`、`source_id` 与原文片段 `quote`；关键结论 MUST 附引用；应用层 MUST 校验引用属于当前问答范围，非法引用 MUST 被丢弃。

#### Scenario: 回答附引用
- **WHEN** 回答中包含基于已确认 Entry 的关键结论
- **THEN** 该结论附带对应的 Entry 与 Source 引用

#### Scenario: 丢弃非法引用
- **WHEN** 模型输出的引用指向范围外或不存在的 Entry / Source
- **THEN** 该引用被丢弃，不进入响应

### Requirement: 知识不足可见
系统 MUST 在知识库不足以回答时明确说明知识不足，不得用模型自身知识悄悄补齐；引用为空且声明不足时 MUST 标记 `insufficient`。

#### Scenario: 知识不足提示
- **WHEN** 当前问答范围内没有足以回答问题的已确认 Entry
- **THEN** 回答明确说明知识不足，不编造内容

### Requirement: 冲突可见
系统 MUST 在检测到问答范围内的已确认 Entry 相互矛盾时并列展示冲突（双方 Entry 与各自观点），不替用户裁决。

#### Scenario: 展示冲突
- **WHEN** 问答范围内存在说法矛盾的已确认 Entry
- **THEN** 回答展示冲突双方及其观点

### Requirement: 可观测性
系统 MUST 在问答响应中记录 `provider` / `model` / `is_fallback` / `error`；未配置密钥或模型调用失败 MUST 明确标记降级原因，禁止静默降级。

#### Scenario: 正常回答记录来源
- **WHEN** 问答由真实文本模型完成
- **THEN** 响应记录 provider 为 `llm`、模型名与 `is_fallback=false`

#### Scenario: 降级回答记录原因
- **WHEN** 问答降级为确定性上下文
- **THEN** 响应标记 `is_fallback=true` 并带降级原因
