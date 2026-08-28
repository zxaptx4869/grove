# knowledge-agent-working-set Specification

## Purpose
TBD - created by archiving change add-knowledge-agent-continuous-follow-up. Update Purpose after archive.
## Requirements
### Requirement: 工作集按用户、Workspace 与范围隔离
系统 MUST 将每个工作集版本归属到一个对话、创建用户和 Workspace，并保存 Workspace/项目范围快照；读取、复用或更新工作集 MUST 同时校验用户、Workspace、对话和范围。

#### Scenario: 读取当前活动工作集
- **WHEN** 对话所有者在同一 Workspace 和范围提交继续追问
- **THEN** 系统可读取该对话的活动工作集作为受控种子

#### Scenario: 尝试复用其他对话工作集
- **WHEN** Run 指向其他用户、Workspace 或对话的工作集版本
- **THEN** 系统拒绝复用且不暴露其中的 Entry 标识或主题

#### Scenario: 项目范围不匹配
- **WHEN** 工作集项目快照与 Run 当前项目范围不同
- **THEN** 系统不加载该工作集作为种子

### Requirement: 工作集使用不可变版本
系统 MUST 以递增、不可变版本保存主题和 Entry 集合；同一对话最多一个活动版本，Run MUST 固化输入版本，并在成功推进上下文时创建新版本而非原地覆盖。

#### Scenario: 继续追问生成新版本
- **WHEN** `continue` Run 产生至少一个有效引用并正常提交
- **THEN** 系统创建以输入版本为父版本的新工作集，关闭旧活动版本并把新版本设为活动

#### Scenario: 恢复中的 Run
- **WHEN** Worker 崩溃后重试同一个 Run
- **THEN** Run 继续使用最初固化的输入版本，不漂移到其他版本

#### Scenario: 查看历史 Run
- **WHEN** 客户端或排障逻辑读取历史 Run
- **THEN** 系统能识别该 Run 的输入与输出工作集版本，即使它们已不再活动

### Requirement: 工作集只保存正式 Entry 线索
工作集项 MUST 只保存正式 Entry 标识、项目/目录/标题短快照、来源 Run、纳入原因与排序元数据；系统 MUST NOT 把助手回答、模型摘要或历史 Evidence 片段作为正式事实存入工作集。

#### Scenario: 有效引用进入工作集
- **WHEN** 本轮最终回答包含服务端核验的 Evidence 引用
- **THEN** 对应正式 Entry 可作为工作集项进入输出版本

#### Scenario: 未引用召回项不进入工作集
- **WHEN** Entry 被召回但未被最终有效引用使用
- **THEN** 系统不因单次召回把该 Entry 长期加入工作集

#### Scenario: 助手回答不成为工作集事实
- **WHEN** 本轮生成一段自然语言回答
- **THEN** 工作集不复制该回答作为后续知识上下文

### Requirement: 工作集有界更新与替换
系统 MUST 对工作集项数量设置服务端上限；`continue` 成功时合并仍有效的旧项与本轮有效引用项并按本轮引用、最近使用排序截断，`new_topic` 成功时 MUST 以本轮有效引用替换旧主题。

#### Scenario: 继续主题合并工作集
- **WHEN** 追问引用旧主题 Entry 和新发现 Entry
- **THEN** 输出版本包含两类有效项且不超过配置上限

#### Scenario: 新话题替换工作集
- **WHEN** 新话题 Run 产生有效引用
- **THEN** 输出版本只围绕新话题的有效引用 Entry，不继承旧主题项

#### Scenario: 超过工作集上限
- **WHEN** 合并后的有效 Entry 多于配置上限
- **THEN** 系统优先保留本轮引用和最近使用项并确定性截断

### Requirement: 无证据结果不得写入工作集项
取消、失败或澄清 Run MUST NOT 创建输出上下文版本；知识不足、回答模型 fallback 或没有有效引用时 MUST NOT 把召回 Entry 写入工作集项。`continue` MUST 保持原活动版本；达到 `completed` 或 `partial` 终态的 `new_topic` MUST 创建仅含主题标签的空版本以承接后续指代，但该标签 MUST NOT 作为事实。事实性回答与可选输出版本 MUST 在同一事务提交。

#### Scenario: 回答被取消
- **WHEN** Run 在任一阶段取消
- **THEN** 当前活动工作集保持不变且不产生半成品版本

#### Scenario: 知识不足
- **WHEN** `continue` Run 没有可核验 Evidence 或最终有效引用为空
- **THEN** 系统不使用召回结果更新工作集项并保持原活动版本

#### Scenario: 新话题知识不足
- **WHEN** `new_topic` Run 明确了新主题但没有有效引用
- **THEN** 系统建立不含 Entry 项的主题版本供下一轮理解指代，且不得把主题标签作为知识事实

#### Scenario: 终态事务失败
- **WHEN** 回答与新工作集版本的最终事务提交失败
- **THEN** 系统既不暴露正常助手回答，也不切换活动工作集

### Requirement: 范围切换关闭工作集
系统 MUST 在对话范围切换事务中关闭当前活动工作集；历史版本保留原范围快照，但 MUST NOT 在新范围自动恢复。

#### Scenario: 项目切换到 Workspace
- **WHEN** 空闲对话从项目范围切换为 Workspace 全部知识
- **THEN** 系统记录范围事件并关闭原项目工作集，新范围下一条消息没有活动工作集种子

#### Scenario: 切回原项目
- **WHEN** 用户后来把范围切回曾使用过的项目
- **THEN** 系统不自动激活历史项目工作集，用户需通过新问题重新建立主题

