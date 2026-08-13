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
| Reader Agent | 节点或项目内阅读、总结和带引用问答 | 已确认 Entry 与 Source 证据 | 即时答案或待确认 Candidate |
| Discovery Agent | 识别缺口、经授权研究外部来源 | 项目上下文、目录、已确认 Entry | 新 Source、Candidate 和发现报告 |

### PydanticAI 的角色

Grove 同时是 PydanticAI 的学习与实践项目，但产品需求决定技术使用方式：

- 用 Pydantic 模型定义 Agent 依赖、工具参数和结构化输出；
- Agent 负责理解、推理、工具选择和生成草稿；
- 普通应用服务负责权限、持久化、事务、幂等和正式数据校验；
- Agent 工具默认只读正式数据，写入目标是 Candidate 或 Draft；
- 确认正式 Entry 或 Directory 的动作由应用服务在用户操作后执行；
- 不为了“像 Agent”引入自主循环、多 Agent 协商或后台无限任务。

### 公共上下文

多个 Agent 共享 Project Context Snapshot，避免各自对项目作出相互矛盾的总结。用户项目说明始终具有最高优先级，AI 项目理解可以自动刷新但必须可见、可纠正。
