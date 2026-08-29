## 1. 前置契约加固

- [ ] 1.1 修复受限调查的 Entry 接纳预算：每轮读取搜索结果前计算剩余额度，read、Evidence、Round 与账本均不得超过 `max_entries`；补充单轮多结果和恢复场景测试，并运行 `cd backend && .venv/bin/python -m pytest tests/test_knowledge_agent_investigation.py tests/test_knowledge_agent_investigation_runner.py -W error`。
- [ ] 1.2 让每条 Investigation Query 的 `result_counts_json` 仅记录本 Query 的 hits、新增 Entry、Evidence、denied 与 unavailable 增量，Round 再汇总；补充多 Query 审计测试，并运行对应调查测试文件。
- [ ] 1.3 将既有 Conversation PATCH 到相同 Workspace/项目范围实现为幂等 no-op，不新增 `scope_change` 消息；补充服务与 API 回归测试，并运行 `cd backend && .venv/bin/python -m pytest tests/test_knowledge_agent_conversations.py -W error`。
- [ ] 1.4 运行 `cd backend && .venv/bin/python -m pytest -W error && .venv/bin/ruff check app tests`，确认前置修复没有回归后按仓库约定完成一次本地提交。

## 2. 对话历史与恢复契约

- [ ] 2.1 将消息历史接口改为无 cursor 返回最近一页且响应内按时间正序；游标以不透明的 before 语义加载更早消息，补充首页、尾页、相同时间戳、无重复/遗漏测试。
- [ ] 2.2 在 `KnowledgeMessagePageOut` 规范化返回本页关联且去重的 `KnowledgeRunOut[]`，让历史用户消息与助手消息通过 `run_id` 复用同一 Run，不产生逐消息 N+1。
- [ ] 2.3 在 `KnowledgeConversationOut` 增加最近 Run 的 id、status、current_step、updated_at 摘要；列表查询批量水合最近 Run，补充查询数量或服务测试证明不会按会话逐条查询。
- [ ] 2.4 运行 `cd backend && .venv/bin/python -m pytest tests/test_knowledge_agent_conversations.py tests/test_knowledge_agent_runs.py -W error && .venv/bin/ruff check app tests`，通过后完成一次本地提交。

## 3. 引用与冲突展示契约

- [ ] 3.1 为 `KnowledgeRunCitationOut` 返回 Evidence 创建时保存的 project_id、project_name、node_path 快照；验证 Workspace 回答中不同项目引用可独立归属，删除当前 Entry/Source 后历史快照仍可展示。
- [ ] 3.2 为冲突项增加完整的 `citation_a` 与 `citation_b`，两侧均含 Source、quote、Entry 与项目/目录快照，同时保留既有兼容字段；补充双边 Evidence、对象已删除和旧响应兼容测试。
- [ ] 3.3 更新回答 schema、组装器和 API 测试，确认 insufficient、partial、fallback 与普通 completed 回答均不因新增字段改变既有语义。
- [ ] 3.4 运行 `cd backend && .venv/bin/python -m pytest tests/test_reader_qa.py tests/test_knowledge_agent_runs.py -W error && .venv/bin/ruff check app tests`，通过后完成一次本地提交。

## 4. 原生 Agent 客户端骨架

- [ ] 4.1 在 `mobile/` 安装并锁定 `expo-crypto` 与 React Native 测试依赖；建立 `src/knowledge-agent/` 的类型、API、query keys、hooks、展示适配器与组件目录，不复制 Web 组件或原型脚本。
- [ ] 4.2 为 conversation、message page、run、answer、citation、conflict、investigation summary 建立与后端一致的 TypeScript 类型和 Bearer API 方法，统一鉴权失效、网络错误、409 与取消错误的可识别结果。
- [ ] 4.3 建立 Conversation draft、稳定 `client_message_id`、一次性模式覆盖、活动 Run 和 AppState 的纯状态模型；使用 `expo-crypto` 生成幂等键，禁止以本地缓存代替服务端权威状态。
- [ ] 4.4 为 API 序列化、最近页合并去重、draft 懒创建、幂等键复用、模式重置和错误分类补充单元测试，运行 `cd mobile && npm test -- --runInBand && npm run lint && npm run typecheck`，通过后完成一次本地提交。

## 5. 会话、历史与范围界面

- [ ] 5.1 用原生组件替换默认对话页的禁用占位态：无历史时进入本地 draft，有历史时恢复最近活动对话；首次成功发送才创建服务端 Conversation，创建成功但提交未知时复用既有 conversation_id。
- [ ] 5.2 实现历史 Bottom Sheet，展示标题、Workspace/项目范围、最近活动、活动主题与最新 Run 状态；支持选择既有对话和新建，不加入重命名、删除、搜索或置顶。
- [ ] 5.3 实现最近消息恢复与向上加载更早消息，按 id 去重并 prepend，保持用户当前滚动位置；范围事件作为居中分隔条，历史回答继续显示各自 Run 范围快照。
- [ ] 5.4 顶栏范围只提供当前 Workspace「全部知识」与项目；draft 先更新本地创建参数，既有对话调用 PATCH；相同范围不发请求/不产事件，活动 Run 时禁用并在服务端 409 后 refetch。
- [ ] 5.5 对话头部展示当前活动主题和工作集 Entry 数，但不展开条目或支持单项移除；为 empty、loading、分页错误、范围错误和恢复状态补充组件测试并运行移动 test/lint/typecheck，随后完成一次本地提交。

## 6. 输入、模式与幂等提交

- [ ] 6.1 实现真实系统键盘输入、发送按钮、可编辑建议问题和提交中的可访问状态；空文本不可发送，长文本与键盘不得遮挡 thread、composer 或底栏。
- [ ] 6.2 实现低频模式 Sheet：理解方式 auto/继续当前主题/新话题，回答方式 auto/快速回答/深度查找；仅非默认值显示可移除 chip，收到确定提交响应后恢复 auto。
- [ ] 6.3 将每次逻辑提交绑定稳定 `client_message_id`：结果未知的网络重试复用原键，终态 failed 的重新提问创建新键；201/幂等 200 均去重合并服务端消息和 Run。
- [ ] 6.4 活动 Run 返回 409 时拉取会话最新 Run，不创建第二个本地任务；为重复点击、超时后重试、创建成功提交失败、幂等重放与模式参数补充测试，运行移动 test/lint/typecheck 后完成一次本地提交。

## 7. Run 过程、取消与前后台恢复

- [ ] 7.1 将服务端 waiting/processing/current_step 映射为准备、理解问题、选择回答方式、检索正式知识、读取 Entry、核验证据、深度查找第 N 轮、综合回答等有限过程文案，不显示 controller reason 或隐藏推理。
- [ ] 7.2 仅在 AppState active 且 Run 未终态时轮询；进入后台停止本地轮询，回到前台、重新登录或重新打开会话时立即 refetch，终态后停止。
- [ ] 7.3 实现活动 Run 取消与「正在取消」过渡态，等待服务端终态；轮询网络失败保留已知 Run 并提供手动重试，不重新提交原问题。
- [ ] 7.4 为前台/后台切换、重启恢复、终态停止、取消竞态、轮询失败与 409 恢复补充 hook/组件测试，运行移动 test/lint/typecheck 后完成一次本地提交。

## 8. 回答、引用与调查结果

- [ ] 8.1 以结构化 `answer.status` 实现 completed、partial、insufficient、failed、clarification 回答卡；Run 完成状态不得掩盖知识不足，fallback 仅显示面向用户的阶段影响与结果。
- [ ] 8.2 实现调查摘要「深度查找 · N 轮 / M 次查询」、停止原因，以及可展开的 coverage、gaps、conflicts；不展示完整 Query 账本、provider/model 原文或调试字段。
- [ ] 8.3 在回答正文下展示真实 citation 来源条，点击打开原生 Bottom Sheet，分区显示 Entry、项目/目录、Source 标题和本次 Run 的原文快照；不伪造段落级内联引用。
- [ ] 8.4 冲突卡展示 citation_a/citation_b 双方原文与归属；历史快照和当前知识跳转结果必须分区标注，对象已删除时仍保留快照且禁用当前对象入口。
- [ ] 8.5 为五种回答状态、降级、不同项目引用、双边冲突、长原文、对象删除与 Sheet 交互补充测试，运行移动 test/lint/typecheck 后完成一次本地提交。

## 9. 视觉、可访问性与设备走查

- [ ] 9.1 依据 `docs/prototypes/grove-mobile-agent-prototype.html` 和 `grove-ui-conventions` 对齐四栏壳、对话默认页、顶栏范围、历史入口、thread、composer、过程/回答卡与 Bottom Sheet；保持本 change 在 design 中记录的只读裁剪和有意偏离。
- [ ] 9.2 在 390×844 主视口及 360×800、412×915 扩展视口走查空态、短/长对话、键盘展开、历史、范围、模式、过程、回答、引用与冲突；不得出现横向滚动、内容截断、顶栏/composer/底栏/系统键盘互相遮挡。
- [ ] 9.3 校验安全区、动态字体/文本缩放、44×44 触控目标、读屏标签、焦点顺序、颜色对比和 reduce-motion；记录 iOS 与 Android 的实际差异，不用伪键盘或网页截图替代原生验收。
- [ ] 9.4 将代表性走查截图和说明放入该 change 的验收产物目录（不提交临时构建包、密钥或 `.env`），运行 `cd mobile && npm test -- --runInBand && npm run lint && npm run typecheck` 后完成一次本地提交。

## 10. 全量验证、验收与收尾

- [ ] 10.1 运行 `cd backend && .venv/bin/python -m pytest -W error && .venv/bin/ruff check app tests`，再用真实 Bearer Session 对 conversation create/list/patch、messages recent/older、submit、run poll/cancel 与 citation/conflict 响应执行 curl 走查，确认预期为 200/201/409 而非 404。
- [ ] 10.2 运行 `cd mobile && npm test -- --runInBand && npm run lint && npm run typecheck && npx expo export --platform ios && npx expo export --platform android`；若本机工具链无法完成设备构建，记录明确缺口并至少完成 Expo bundle/export 与真机或模拟器走查之一，不以静默跳过代替验证。
- [ ] 10.3 手动走查 draft 首次发送、最近会话恢复、向上分页、范围切换、连续追问、quick/auto/investigate、前后台恢复、取消、断网幂等重试、五种回答状态、引用、冲突和三个目标视口，并把结果写入该 change 的 validation 记录。
- [ ] 10.4 运行 `openspec validate add-native-knowledge-agent-conversation --strict` 与 `openspec validate --all --strict`；逐项核对 tasks、spec scenarios、原型偏离和产品专题，发现遗留项时按 AGENTS.md 先向用户说明并询问是否登记。
- [ ] 10.5 完成最终本地提交并停留在特性分支等待用户验证；只有用户明确确认后才执行 OpenSpec archive、最终归档提交、push 或合并。
