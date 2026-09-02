# knowledge-agent-follow-up Specification

## Purpose
TBD - created by archiving change add-knowledge-agent-continuous-follow-up. Update Purpose after archive.
## Requirements
### Requirement: 每条消息产生可见上下文决策
系统 MUST 为每条被接受的用户消息保存请求的上下文模式与实际决策；请求模式 MUST 支持 `auto`、`continue`、`new_topic`，实际决策 MUST 为 `continue`、`new_topic` 或 `clarify`，并向有权客户端返回主题标签、独立检索查询、输入工作集版本和降级状态。

#### Scenario: 自动识别继续追问
- **WHEN** 用户以 `auto` 提交与活动主题明显相关的追问
- **THEN** 系统保存 `continue` 决策、当前主题标签与补全后的独立检索查询

#### Scenario: 自动识别新话题
- **WHEN** 用户以 `auto` 提交与活动主题无关的完整问题
- **THEN** 系统保存 `new_topic` 决策且不把旧工作集作为本轮检索种子

#### Scenario: 查询 Run 查看上下文
- **WHEN** 客户端查询已产生上下文决策的 Run
- **THEN** 响应返回请求模式、实际决策、主题、独立查询、输入版本及是否降级

### Requirement: 用户显式模式覆盖自动判断
系统 MUST 将 `continue` 与 `new_topic` 视为用户确定性指令；分类模型 MUST NOT 改变显式模式的语义，且重复提交同一 `client_message_id` MUST 返回首次保存的模式与决策。

#### Scenario: 强制继续当前主题
- **WHEN** 对话有活动工作集且用户以 `continue` 提交问题
- **THEN** 系统沿用该工作集并只使用模型补全独立查询

#### Scenario: 强制开始新话题
- **WHEN** 用户以 `new_topic` 提交问题
- **THEN** 系统在提交事务关闭旧活动工作集并以当前消息开始独立检索

#### Scenario: 重试时改变模式
- **WHEN** 客户端以相同 `client_message_id` 重试但提交不同 `context_mode`
- **THEN** 系统返回首次创建的消息与 Run，不改写已保存模式或重新执行

### Requirement: 有限历史只用于意图理解
系统 MUST 只向上下文决策阶段提供配置上限内的近期消息、活动主题和工作集标题；回答阶段只能接收服务端从同一 Conversation、同一范围快照、当前上下文链中选出的有界用户消息，以及本 Run 重新读取的正式 Entry/Evidence。历史助手回答 MUST NOT 直接进入回答事实上下文、被标记为用户陈述或作为正式知识引用；系统 MUST 保存上下文决策实际使用的消息 ID 与最终作为用户陈述依据的消息 ID。

#### Scenario: 解析省略指代
- **WHEN** 用户追问“它为什么更适合”且近期消息与活动主题能确定“它”的含义
- **THEN** 上下文决策可据此生成包含明确对象的独立查询或开放回答问题

#### Scenario: 继续话题使用用户陈述
- **WHEN** 当前决策为 `continue`，近期用户消息包含回答所需的个人前提且该消息仍在服务端允许集合内
- **THEN** 依据规划器可以选择该消息，回答将其标记为“用户提供的信息”并保存消息 ID

#### Scenario: 历史回答包含无引用说法
- **WHEN** 近期助手消息含有未被当前 Run Evidence 支持的说法
- **THEN** 回答阶段不把该说法当作用户陈述或独立事实，只能使用本轮允许的用户消息、模型通用知识和重新读取的正式 Entry/Evidence

#### Scenario: 新话题切断旧用户陈述
- **WHEN** 当前决策为 `new_topic`
- **THEN** 回答阶段只允许当前用户消息，不把旧上下文链中的用户陈述作为本轮形成依据

#### Scenario: 历史超过上限
- **WHEN** Conversation 历史超过配置的消息数量或单条长度
- **THEN** 系统只使用稳定选取并截断后的有限历史，同时分别保存上下文决策和实际用户陈述所用消息 ID

### Requirement: 追问改写为可独立检索查询
系统 MUST 为 `continue` 决策生成非空的 `standalone_query`，使其脱离聊天记录仍表达本轮检索目标；原始用户消息 MUST 保持不变，改写结果只能作为 Run 检索输入。

#### Scenario: 成功改写追问
- **WHEN** 用户在“闭水试验时长”主题下追问“为什么不能提前放水”
- **THEN** 系统保存包含闭水试验对象的独立查询，并保留原始追问消息供展示

#### Scenario: 改写模型不可用
- **WHEN** 用户强制 `continue` 但上下文模型未配置或调用失败
- **THEN** 系统用主题标签与当前消息形成确定性独立查询、标记降级并继续执行

### Requirement: 歧义通过澄清回复处理
系统 MUST 在无法安全确定追问对象或用户强制继续但没有活动工作集时返回澄清回复；澄清 Run MUST NOT 执行知识检索、生成事实引用或更新工作集。

#### Scenario: 自动判断需要澄清
- **WHEN** `auto` 消息含有无法从有限上下文解析的指代
- **THEN** 系统返回 `answer.status=clarification` 的具体澄清问题并正常结束 Run

#### Scenario: 无工作集强制继续
- **WHEN** 对话没有活动工作集且用户提交 `context_mode=continue`
- **THEN** 系统请求用户补充主题，不猜测或读取无关历史对象

#### Scenario: 澄清不推进上下文
- **WHEN** Run 以澄清回复结束
- **THEN** 输入工作集保持不变且 Run 不产生输出工作集版本

### Requirement: 上下文决策可观测且安全降级
系统 MUST 记录上下文决策/改写阶段的 provider、model、prompt 版本、fallback、错误和耗时；`auto` 模型不可用时 MUST 显式降级为 `new_topic`，不得静默沿用旧工作集。

#### Scenario: 真实模型完成判断
- **WHEN** 自动上下文决策由配置的模型成功完成
- **THEN** 阶段记录实际 provider/model 与 `is_fallback=false`

#### Scenario: 自动判断模型失败
- **WHEN** 自动上下文模型未配置、超时或结构校验失败
- **THEN** 系统记录失败原因、决策为 `new_topic` 并在 Run 汇总中标记降级

