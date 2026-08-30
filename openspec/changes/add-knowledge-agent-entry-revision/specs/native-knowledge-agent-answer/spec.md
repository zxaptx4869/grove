## ADDED Requirements

### Requirement: 回答引用详情提供 Entry 定向后续操作
原生回答的 citation 详情 MUST 在当前 Entry 可用于写入时提供结构化“修订这条知识”动作，并把 target_entry_id 与 source_run_id 绑定到服务端已返回对象；客户端 MUST NOT 允许用户或模型自由填写对象 ID。该动作不改变 citation 的阅读与原文核验主用途。

#### Scenario: 当前有效引用显示修订动作
- **WHEN** completed/partial 回答的 citation 对应当前可写 Entry
- **THEN** 引用详情在 Entry/Source 原文之后提供目标明确的修订入口

#### Scenario: 只查看来源原文
- **WHEN** 用户打开 citation 但不发起修订
- **THEN** 页面只展示 Entry 与 Source Evidence，不创建 Draft、Run 或任何写对象

### Requirement: 回答、Candidate Draft 与 Entry Revision 语义不混淆
原生 App MUST 将“整理成知识”表达为创建待确认 Candidate，将“修订这条知识”表达为对既有正式 Entry 的候选修改；两种动作、草稿、确认后果与回执 MUST 使用不同标题和文案，MUST NOT 把任一 AI 草稿显示为已执行。

#### Scenario: 同一回答提供两类后续动作
- **WHEN** 回答既可整理为 Candidate 且某条 citation 可修订
- **THEN** 页面分别说明“创建待确认知识”和“修改现有正式知识”，用户能看懂目标及确认后果

#### Scenario: Entry Revision 尚未确认
- **WHEN** 修订草稿已生成但未应用
- **THEN** 回答与 Entry 仍保持正式原内容，草稿标识为 AI 建议且不显示已更新
