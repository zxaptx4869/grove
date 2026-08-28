# Agent 架构与 AI 边界

[返回产品蓝图索引](../产品蓝图.md)

> 权威范围：Project Context Snapshot、专业 Agent 职责、PydanticAI 角色与公共上下文。

## Project Context Snapshot

供多个 Agent 共享的派生上下文，不是正式知识，也不覆盖用户说明。

建议结构：

```text
ProjectContext
├── user_description       用户项目说明，原文优先
├── project_summary        AI 项目概要
├── current_focus          当前关注方向
├── directory_topics       目录主题
├── knowledge_coverage     已确认知识覆盖
├── recent_topics          最近整理主题
├── lifecycle_status       生命周期状态
└── generated_at           更新时间
```

只使用正式目录和已确认 Entry 生成，不使用待确认 Candidate。目录或知识发生重要变化后异步、防抖更新；失败时继续使用上一份有效快照。用户可以查看、纠正和重新生成，纠正内容作为高优先级约束保留。

## Agent 产品架构

产品不向用户强调多个 Agent，但技术职责应分离，不做一个全能 Agent。

| Agent | 核心职责 | 只读上下文 | 输出边界 |
|---|---|---|---|
| Organizing Agent | 解析、语义拆分、价值筛选、项目和目录推荐、关系判断 | Source、项目上下文、目录、已有 Entry | Extraction、Candidate 和归档建议 |
| Directory Agent | 起草、拓展和调整目录 | 项目上下文、目录、已确认 Entry、Source 摘要 | Directory Draft 与结构化操作 |
| Knowledge Agent（Reader 演进） | Workspace 或项目内阅读、总结和带引用问答；后续承载连续追问与受限调查 | 已确认 Entry、真实 Source 证据与项目上下文 | 可恢复的即时答案；知识写入必须另走待确认 Candidate |
| Discovery Agent | 识别缺口、经授权研究外部来源 | 项目上下文、目录、已确认 Entry | 新 Source、Candidate 和发现报告 |

### PydanticAI 的角色

Grove 同时是 PydanticAI 的学习与实践项目，但产品需求决定技术使用方式：

- 用 Pydantic 模型定义 Agent 依赖、工具参数和结构化输出；
- Agent 负责理解、推理、工具选择和生成草稿；
- 普通应用服务负责权限、持久化、事务、幂等和正式数据校验；
- Agent 工具默认只读正式数据，写入目标是 Candidate 或 Draft；
- 确认正式 Entry 或 Directory 的动作由应用服务在用户操作后执行；
- 不为了“像 Agent”引入自主循环、多 Agent 协商或后台无限任务。

### Knowledge Agent 的演进边界

Knowledge Agent 是 Web 与原生 App 共用的知识交互能力，不再把“AI 阅读”理解成某个目录页面上的一次性生成器。用户可选范围只有当前 Workspace「全部知识」和具体项目；目录继续存在，但仅承担 Agent 内部检索定位、结果归属和知识浏览，不作为对话范围选择项。

演进按可验证纵向能力逐步推进：

1. 先建立持久化对话、独立问题的只读 Run、可信检索工具与可核验 Evidence；每个问题独立检索，不把历史回答当作正式知识。
2. 再增加追问关系判断、显式工作集和有限上下文，让用户能够围绕同一主题连续提问。每条消息明确判断为继续、新话题或需要澄清；用户可以覆盖自动判断。工作集只保存当前主题涉及的正式 Entry 线索并按 Run 版本化，历史回答只帮助理解指代，不能直接成为事实或复用为新引用。
3. 在成本、取消、证据与恢复机制稳定后，才增加有轮次上限的自主调查，例如改写查询、补找依据和检查冲突；仍不允许后台无限运行。
4. 知识增删改始终作为独立工具族建设。AI 只能产出 Candidate 或 Draft，正式写入继续由应用服务校验并由用户确认。

一次 Run 的执行记录必须可持久化、可恢复、可取消，并分阶段记录搜索、重排、工具与回答模型的 provider、model、fallback 和错误。模型不能自行指定 Workspace 或项目范围，也不能仅凭猜测的对象标识读取知识。

最终引用必须来自本 Run 实际读取的 Source/Attachment 原文 Evidence。模型只选择服务端生成的 Evidence 句柄，不能自由生成 `quote`；无法核验的来源不能包装成可信引用。

连续追问也不降低这条证据边界：上一轮工作集只提供检索种子，本轮必须重新校验 Entry 范围、重新读取 Source/Attachment 并生成新的 Run Evidence。范围切换和用户显式开始新话题会切断旧工作集；失败或澄清不推进上下文，无有效引用时不能加入任何 Entry，但新话题可保留一个不作为事实的空主题标签以理解下一句指代。

### 公共上下文

多个 Agent 共享 Project Context Snapshot，避免各自对项目作出相互矛盾的总结。用户项目说明始终具有最高优先级，AI 项目理解可以自动刷新但必须可见、可纠正。
