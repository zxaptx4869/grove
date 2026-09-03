## MODIFIED Requirements

### Requirement: 每条普通消息明确请求与实际结果形态
系统 MUST 为普通 answer Run 接受 `auto`、`answer`、`entries` 三种 `result_mode`，默认 `auto`；系统 MUST 分开持久化请求形态与实际形态。`auto` MUST 在上下文决策得到独立问题后，由结构化结果形态路由判断最终展示为综合回答或 Entry 结果：纯对象查找、纯结构化筛选/计数/排序/分组可以路由为 `entries`；同时要求解释、比较、建议、个人知识综合或其他叙述性回答的混合请求 MUST 路由为 `answer`，再由复合回答计划在内部使用所需只读能力。显式 `answer`/`entries` MUST 跳过自动结果形态路由且不得被模型改写，显式 `entries` 内部仍可执行受限结构化查询规划。

#### Scenario: 自动判断为查找对象
- **WHEN** 用户询问“帮我找出个人健康项目里和血压有关的知识”且未覆盖结果形态
- **THEN** Run 保存 `request_result_mode=auto`、`actual_result_mode=entries` 并进入结构化 Entry 查找执行图

#### Scenario: 自动判断为综合回答
- **WHEN** 用户询问“这些血压记录说明了什么”且未覆盖结果形态
- **THEN** Run 保存 `actual_result_mode=answer` 并继续 quick 复合回答或既有 investigate 路径

#### Scenario: 混合解释与统计保留为回答
- **WHEN** 用户要求解释一个概念、结合个人知识分析，并统计相关正式知识数量
- **THEN** 自动路由选择 `answer`，统计由内部受控结构化工具提供，系统不因出现“统计”就丢弃解释义务或只返回 Entry 结果

#### Scenario: 用户显式覆盖结果形态
- **WHEN** 用户对下一条消息明确选择“知识列表”或“综合回答”
- **THEN** 系统使用该显式形态，不调用结果形态路由，并把覆盖值随该消息和 Run 保存

#### Scenario: 结果形态路由失败
- **WHEN** `auto` 路由未配置、超时、调用失败或输出非法结构
- **THEN** 系统显式记录 provider/model/fallback/error，安全回退 `answer`，不得静默伪装为成功路由或凭关键词执行隐藏写操作

#### Scenario: 自动判断为纯结构化统计
- **WHEN** 用户只询问“最近半年有多少条个人经验，按月分组并列出最近五条”且未要求解释或综合
- **THEN** 系统可以将实际结果形态设为 `entries`，再由受限结构化查询计划表达统计、分组和列表，不让结果形态路由直接生成数字
