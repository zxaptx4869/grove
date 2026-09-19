## 1. 正式对话合同

- [ ] 1.1 收敛原生 Knowledge Run、Message Page、submission 与上下文设置类型，只保留正式对话需要的字段并接入 `dialogue_loop_status`、`dialogue_stage`、`dialogue_blocks` 和 `can_continue`
- [ ] 1.2 实现按服务端原序渲染 text、list、statistic、entry、evidence、candidate/candidate_text_only、insufficient 及未知块安全降级，避免与扁平回答重复
- [ ] 1.3 用真实 dialogue 阶段和终态更新过程卡，覆盖 completed、partial、failed、cancelled、not_executed、unsupported 与网络未知状态

## 2. Entry 阅读与恢复

- [ ] 2.1 对 `result_type=entries` 且有 `entry_id` 的列表项实现原位按需正文读取、收起、加载、失败重试和当前不可访问状态，保持服务端顺序与序号
- [ ] 2.2 区分列表快照、Entry block、本次 Evidence 和当前 Entry 来源信息，确认展开只调用只读 Entry API且不提交消息或模型请求
- [ ] 2.3 通过普通消息管线实现绑定当前 Conversation/Run 的 continuation，并保持结果未知重试与失败后重新提问的不同幂等语义
- [ ] 2.4 保留并验证会话切换、范围、分页、取消、前台轮询、后台停止轮询和重启服务端恢复

## 3. 删除旧移动业务

- [ ] 3.1 删除 Candidate Draft 创建、编辑、确认、取消、重试、回执及其 API、控制器状态、组件、类型和专用测试
- [ ] 3.2 删除 Entry Revision 发起、编辑、差异确认、应用、撤销、回执及其 API、控制器状态、组件、类型和专用测试
- [ ] 3.3 删除旧 citations、复杂 answer/entry_result 适配、专用详情与分页，以及快速/深度、结果形式、依据模式、结果纠正的状态和测试
- [ ] 3.4 静态核对运行时移动端不再引用或调用上述知识写接口，且共享后端服务与 Web 调用方未被修改

## 4. 规格、测试与证据

- [ ] 4.1 更新 `技术与端侧边界.md` 中原生对话职责，记录本轮方案二对旧产品描述的替代
- [ ] 4.2 更新移动单元/组件/控制器测试，覆盖块顺序、对象列表语义、Entry 按需展开、Evidence 与候选语义、终态、continuation、幂等重试、会话切换和前后台恢复
- [ ] 4.3 运行移动相关测试、typecheck、lint，执行收尾 `openspec validate --all --strict` 与 `git diff --check`
- [ ] 4.4 在不重启服务的前提下检查可用正式配置；有授权凭据时完成少量真实 DeepSeek 普通问答、知识列表、指定条目和候选改写验证并记录 Conversation/Run/模型/fallback，确认 Entry 展开不触发模型；无凭据或服务不可用时如实记录
- [ ] 4.5 持续维护 `docs/discussions/移动端对话模块精简与正式Agent对齐-2026-09-19.md`，记录基线、替代决定、删改范围、验证证据、限制、提交号和用户设备走查清单

## 5. 阶段提交与设备验收

- [ ] 5.1 按可验证阶段完成本地中文 Conventional Commits 提交，不纳入既有无关工作区修改或本地讨论文档
- [ ] 5.2 自动化完成后报告“实现与自动化验证完成，待设备验收”，等待用户按清单验证列表展开、长正文、键盘、安全区、返回、前后台与异常恢复；验收前不归档、不推送、不合并
