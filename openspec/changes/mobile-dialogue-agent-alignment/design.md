## Context

正式 Worker 已只走统一 dialogue loop，并在 Run 响应中公开 `dialogue_loop_status`、处理中 `dialogue_stage`、有序 `dialogue_blocks`、`can_continue` 和不透明 `continuation`。原生端仍围绕旧 `answer/citations/entry_result` 与两类持久草稿组织类型、控制器和界面，导致正式回答退化成扁平文本，且大量不可达写逻辑继续占据运行时模块。

本设计采用用户确定的方案二：保留原生基础设施和一致的交互基线，替换知识对话业务模块，不保留新旧双轨。依据与删改范围来自本 change 规格及 `docs/discussions/移动端知识Agent现状与对齐摸排-2026-09-18.md`，其中“恢复旧 Candidate/Revision 入口”等建议已被本轮产品决定替代。

## Goals / Non-Goals

**Goals:**

- 以正式 dialogue 合同恢复当前 Conversation 的历史、阶段、终态、块和 continuation。
- 用现有原生主题与基础组件展示正式块，并让明确 Entry 列表按需原位读取当前正文。
- 从移动运行时代码中删除旧 Candidate Draft、Entry Revision、citations、旧 Entry Result 和未生效模式业务。
- 保留登录、Bearer、安全存储、会话/消息分页、范围、消息幂等、前台轮询、取消、前后台及重启恢复。

**Non-Goals:**

- 不修改共享 loop、提示词、预算、模型、工具、Candidate/Revision 服务或数据库。
- 不增加写操作、Operation Review、能力感知、第二套记忆或客户端关键词路由。
- 不实现移动收集、待处理、知识主页面，不迁移或删除测试数据。
- 不重设计 App 壳层，不升级依赖，不用模拟器或真机替代用户验收。

## Decisions

### 1. Run 类型保留服务端兼容外形，移动业务只处理普通对话

移动端 `KnowledgeRun` 继续允许服务端返回兼容字段，但 UI 和控制器只把普通回答 Run 作为正式对话内容；消息页即使仍携带 `candidate_drafts` 或 `entry_revision_drafts`，客户端也忽略，不建立 map、不轮询、不恢复卡片。这样不要求后端为单一客户端改变消息页，同时真正删除移动写业务。

备选是修改后端按客户端裁剪响应；它会扩大共享合同并无助于本轮用户价值，故不采用。

### 2. 使用小而明确的 block 联合类型与本地防御性读取

在移动类型层声明正式已知块及公共字段，同时允许 `unknown` kind 的安全占位。渲染器按数组原序逐块输出，不按类型分组：

- `text`：普通即时回答文本；
- `list`：按 `result_type/semantics.subject` 区分 projects、directories、entries；只对 entries 中带数值 `entry_id` 的项开放正文读取；
- `statistic`：展示服务端 value/buckets/completeness，不由客户端重算；
- `entry`：展示回答生成时已读取的正文快照，不再重复请求同一内容；
- `evidence`：只按公开 `text/entry_id/source_id` 表达本轮核验材料，不拆自然语言；
- `candidate` 与兼容 `candidate_text_only`：统一显示“AI 候选稿/修改建议 · 未应用”；
- `insufficient`：显示材料不足边界；
- 未知/无效块：单块占位，其余块继续显示。

存在至少一个可展示块时不渲染完整扁平 answer；无块时只显示简单文本回退，不恢复 points、citations、conflicts 或 answer_basis。

备选是复制 Web renderer。Web 的 DOM 结构和执行记录不适合原生端，而且会把桌面布局带入移动；本轮只复用合同判断，不复制实现。

### 3. Entry 列表在原位按需读取当前正文

新增一个对话块组件维护每项展开状态，并在展开项内部使用现有 TanStack Query key 与 `getEntryCurrent`。请求只在该项首次展开时启用；加载、错误、重试、不可访问和来源摘要都留在原列表位置。服务端块顺序、items 顺序和 index 生成的序号不因展开改变。

展开区固定标注“当前知识内容”；Entry block 则标注“本轮读取的知识正文”。当前 Entry 返回的来源摘要标注“当前知识的来源”，不等同于本轮 Evidence。展开动作只触发 GET，不调用消息提交或模型接口。

备选是继续使用全屏/Sheet 详情；它不满足本轮“原位展开”，因此仅复用其中的只读查询和文案边界，删除专用 Sheet。

### 4. continuation 复用普通消息提交管线

继续按钮只渲染在其所属 Run 卡上，并由控制器验证该 Run 属于当前 Conversation、是会话 `recent_run_id` 指向的最新可恢复 Run（旧响应无该字段时退回当前已加载页中更新时间最新的可恢复 Run）、`can_continue=true` 且没有活动 Run。点击后通过现有 pending submission 管线发送正文“继续”，生成新的 `client_message_id`；客户端不读取、复制或修改 `continuation`。

网络结果未知仍重放 pending submission 的原键；失败后重新提问与 continuation 都新建键。会话切换清除本地按钮动作上下文，显示完全由新 Conversation 的服务端页决定。

### 5. 只保留 context_mode 设置

`ModeSelection` 收敛为 `contextMode`；提交 API 仅显式发送当前后端有准确语义的 `context_mode`。后端 schema 的兼容默认值无需改动。快速/深度、结果形式、basis、source_run_id 纠正状态和所有对应 chip/测试删除。

备选是继续提交 auto 占位字段但隐藏 UI；这会保留误导性业务模型和未来双轨入口，不符合“删除不再使用的旧实现”。

### 6. 不修改后端

本轮展示所需的状态、块、continuation 和 Entry 当前只读接口均已存在。Evidence 的公开字段不足以重建旧引用 Sheet，但本轮明确禁止重建 citations 或从文本解析元数据，因此不是阻塞项。若后续产品需要 Source 标题、quote、附件或历史快照的独立交互，应另立后端 typed Evidence 合同 change。

### 7. 历史页与异步回调绑定会话代次

`olderPages` 按请求返回顺序保存为“较近旧页 → 更早旧页”，组合线程时也按该顺序逐页前插，使消息保持时间正序并让最终游标来自最早已加载页。页间消息仍按 id 去重，Run 仍按更新时间归并。

分页、范围切换和取消等会写入共享本地状态的异步请求在发起时记录 Conversation 与本地会话代次；切换会话、新建对话或重置当前对话状态时同步推进代次。迟到响应可以更新其自身服务端查询缓存，但不得再改写当前页面的旧页、Run、loading、busy、cancelling 或错误状态。普通消息提交因 pending 期间禁止切换会话，继续沿用既有幂等提交边界。

## Risks / Trade-offs

- [旧测试 Run 没有 blocks 时信息减少] → 只保留扁平文本回退；移动端尚未上线，接受不恢复旧复杂交互。
- [公开 list item 为弱类型字典] → 仅使用经类型守卫确认的字段，未知对象只读展示或占位，绝不据此发起写操作。
- [Entry 当前内容与历史块不同] → 分别标注“当前知识内容”和“本轮读取/生成时结果”，不覆盖历史块。
- [旧 operation Run 仍出现在消息页 runs] → UI 不渲染其草稿或写回执；普通正式回答 Run 的恢复不受影响。
- [真实 continuation 不易稳定触发] → 用确定性控制器/组件测试覆盖，真实调用记录为未自然覆盖，不反复消耗模型制造失败。

## Migration Plan

1. 先提交完整 OpenSpec 工件并通过全库严格校验。
2. 新增正式 block 类型、渲染和 Entry 按需读取；改造阶段/终态与 continuation。
3. 收敛提交设置与线程状态，删除 Candidate/Revision/citation/旧 Entry Result 业务及专用测试。
4. 更新产品端侧专题、移动测试与本地讨论交付记录。
5. 运行移动端相关测试、typecheck、lint、OpenSpec 严格校验和 `git diff --check`；在已有服务和凭据可用时做少量真实正式链路检查，不启动或重启服务。
6. 本地提交后等待用户设备验收；未验收前不归档、不推送、不合并。

回滚使用 Git 恢复本 change 的移动端提交；不涉及数据库迁移或业务数据回滚。

## Open Questions

无阻塞产品问题。Evidence 若未来需要独立 Source 快照详情，必须另行决定 typed 后端字段与交互范围，不在本 change 内预留双轨。
