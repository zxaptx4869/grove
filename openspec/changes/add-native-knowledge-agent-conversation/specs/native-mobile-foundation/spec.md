## MODIFIED Requirements

### Requirement: 真实 Workspace 范围与项目数据
移动对话首页 MUST 读取 `/api/me` 的真实 Workspace 与 `/api/projects` 的真实项目列表，并通过统一 `/api/knowledge-agent` 协议使用真实 Conversation、Message、Run 与 Evidence。用户可见知识范围 MUST 只有 Workspace 的“全部知识”和具体项目，不得暴露目录节点范围；收集、待处理和知识栏目在各自能力接入前 MUST 继续显示真实未接入状态，不得模拟业务记录。

#### Scenario: 项目加载后切换草稿范围
- **WHEN** 认证用户在新对话打开范围选择并选中一个项目或“全部知识”
- **THEN** 当前范围立即以清晰文字显示，选择项只包含全部知识和该 Workspace 的项目，首次发送按该范围创建真实对话

#### Scenario: 对话页调用统一 Agent
- **WHEN** 用户在原生对话页提交问题
- **THEN** App 调用统一知识 Agent Conversation/Run API，不调用旧 Reader API、不使用模拟回答

#### Scenario: 未接入业务栏目不伪造数据
- **WHEN** 用户进入收集、待处理或知识栏目
- **THEN** 系统显示该能力尚未接入的真实状态与下一步说明，而不是静态业务记录

