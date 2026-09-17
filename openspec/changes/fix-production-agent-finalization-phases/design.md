## Context

旧 Agent 编排已退役，正式 answer Run 与实验台都使用 `backend/evals/dialogue_loop`。当前统一循环已经具备无工具 finalizer、内存/生产快照 continuation、结果句柄授权、严格输出校验和 activity callback，但三处连接不完整：软阈值捕获对未筛选候选提前返回；Provider 的 `INVALID_JSON` 包装没有安全兼容；正式适配器没有传播 callback 阶段且把 `finalize_transition` 误记成模型失败。

真实证据来自 `docs/discussions/生产Agent软阈值阻断收尾-清理后优先修复-2026-09-16.md` 及本地实验台会话 `session-20260916-130250`。生产 Run 13 的关键投影是 8295 → 9290；实验台第 4 轮保存了 1002 字符 `INVALID_JSON` 内层文本，其未转义引号使标准解析在第 1120 列附近失败。

## Goals / Non-Goals

**Goals:**

- 在不增加预算的前提下保住安全文本、隔离未筛选候选并提供准确恢复。
- 用同一组确定性夹具验证共享循环、实验台和 production adapter。
- 把已有真实阶段以最小正式 API 状态传到 Web，并保持 Worker 恢复合同。

**Non-Goals:**

- 不接入 Entry 写入、不改变 Source/权限/Workspace 隔离、不新增意图或规划模型。
- 不提高输入、模型请求、工具、正文、Evidence、时间或重试预算。
- 不新增编排器、数据库列或右侧诊断面板，不修改移动端和历史 change。

## Decisions

### 1. 将可保留文本与完整输出授权分层

普通输出校验器在抛出 `ModelRetry` 前，提取只含 `text`/`insufficient` 的受限草稿；只有文本自身满足通用知识、写入声明和当前编辑边界时才保存。列表、Entry、Evidence、结果句柄及候选标题一律不进入草稿。最终交付仍必须重新通过完整 `DialogueAnswer`、句柄、权限与来源校验。

这比接受整个失败输出安全，也比完全丢弃更符合现有 candidate draft 保存模式。草稿放入 `LoopState` 和 continuation 的有界私有材料，不公开原始响应。

### 2. 软阈值始终进入既有 finalizer，pending 只决定材料与恢复语义

移除 `FinalizeRequired` 捕获处对 pending candidate 的提前失败。`_current_material_history` 继续跳过 `displayable=false` 候选，另向 finalizer提供受限文本；因此无工具收尾无法看到或引用候选。若任务不依赖候选，可完整回答并按输出判定完成；若必须依赖候选，则保留 `relevance_selection_pending`，同时建立 `relevance_selection` continuation。

不新增第二个流程。续接仍由 `run_turn()` 分派：恢复候选记录和原查询摘要后，用现有 `select_relevant_entries` 合同完成筛选，再进入同一个 finalizer。恢复态禁止资料派发；成功查询只作为已保存事件和候选输入，不再次执行。

### 3. 候选 continuation 使用内容指纹与数据库复验

最小私有材料保存候选记录、原查询事件、原问题和候选 Entry ID；公开快照只保留计数、任务类型和待办。恢复时先验证 Workspace、用户、项目范围、记录句柄和指纹，再通过既有数据库权限路径读取候选 Entry 的当前身份/版本指纹。任何缺失、越权或变化都返回 `continuation_material_invalid`，不搜索替代。

这沿用现有 finalize continuation 的 `validation_refs` 与 `_database_material_refs`，不建立通用任务系统。

### 3.1 已授权 Entry 的跨轮发现集与指纹一起恢复

生产快照只保存 `authorized_entry_ids ∩ discovered_entry_ids` 中同时具备服务端 Entry 指纹的对象，恢复时把该子集及指纹注入既有 `LoopState` 和 `RunToolContext`。旧快照或候选结果缺少这组交集与指纹时不追认可读取身份。

`read_entries` 在返回正文前继续查询 Workspace 成员关系，并复验 Entry 所在 Workspace、当前项目范围、对象存在性及 `entry_baseline` 指纹。完整成功的同组后续读取可在轮次终态计算中消解早先的临时拒绝事件，但审计事件仍保留；没有后续完整成功证据的权限拒绝不被消解。

### 4. `INVALID_JSON` 兼容位于 Provider 响应归一化层

扩展现有 `_normalize_legacy_answer_response()` 所在的请求返回边界，仅识别“唯一 output tool call、参数字典恰有一个 `INVALID_JSON` 字符串字段”。使用 `json.loads` 严格解析后要求顶层键属于当前 `DialogueAnswer`，再构造标准 `ToolCallPart` 交给 PydanticAI 和既有 output validator。

内层损坏、未知字段、多个响应 part、资料工具或非法引用均不转换。原始 public response 和兼容事件继续进入审计；不使用 JSON repair、正则正文提取或补全括号。

### 5. 用户阶段保存在现有 dialogue-loop 快照

新增 API 字段 `dialogue_stage`，来源为 `dialogue_loop_state_json.stage`，不新增数据库列。生产适配器安装一个有序、去重的异步阶段发布器：同步 callback 只入队；单消费者在阶段变化时用独立短会话更新 processing Run 快照，并在主执行终态写入前关闭等待。终态快照不含活动 `stage`，因此刷新和切换不会恢复旧动效。

`current_step` 在整个循环期间保持 `dialogue_loop`，继续由 Worker 判断恢复安全。阶段写入最多发生于真实状态转换，避免 token/事件级高频写入。

Web 复用现有 Badge、`LoaderCircle`、语义色和消息内状态行；阶段映射集中定义，未知或缺失阶段回退为“正在准备本轮回答”。动效增加 `motion-reduce:animate-none`，状态容器使用礼貌播报，不改变页面结构。

### 6. 审计按是否派发分类

`finalize_transition` 与 `text_not_dispatched` 同属 `MODEL_NOT_DISPATCHED`；错误文本仍保存用于说明停止原因，但不设置 fallback。只有实际 `text` 请求的 Provider/timeout/protocol 错误记为 `MODEL_CALL_FAILED`。不依据错误字符串猜测分类。

### 7. 失败兜底有界化并保留异常现场

`_verified_failure_output()` 按 `DialogueAnswer` 的 12 块上限预留首部状态说明与末部缺口说明，优先保留已通过边界检查的候选稿/通用文本，再按稳定顺序选取已确认结果与 Evidence；超出展示容量的材料仍保留在生产快照，不通过放宽 schema 交付。这样校验失败后的兜底不会因自身块数再次抛异常。

正式适配器的最后异常边界从当时 `LoopState` 生成有界失败快照，保留此前历史、已授权结果、continuation、工具事件和当前 instrumentation 模型日志，并只写入异常类型、稳定错误码及 Pydantic 错误位置/类型等脱敏诊断，不保存 traceback、原始 prompt 或私密模型响应。模型审计照常落库，避免空失败快照覆盖恢复依据。

若上一轮失败，只有显式 continuation 指令才激活其 continuation 和恢复材料；普通明确新问题从干净的当前轮句柄与模型消息历史执行，不自动续做失败任务。该隔离仅切断失败任务的执行上下文，不改变已授权 Entry 的服务端恢复集合，也不新增意图模型或草稿记忆能力。

## Risks / Trade-offs

- [阶段短事务与终态提交竞争] → 单消费者保证顺序，关闭发布器后再写终态，并用 `status=processing` 条件更新避免覆盖终态。
- [保留文本可能夹带未授权内容] → 仅允许无结构块文本，执行候选标题泄漏、写入声明、编辑范围和通用知识边界检查；最终仍走完整校验。
- [恢复时候选已变化] → 使用句柄内容指纹和数据库对象指纹双重校验，变化即失效，不自动重搜。
- [严格解包覆盖面有限] → 有意只兼容已观察且可证明安全的包装；损坏样本继续失败并由 continuation 恢复。
- [异常快照可能携带敏感上下文] → 只保存既有有界状态和结构化脱敏诊断，模型原始响应仍沿用既有公开审计裁剪，不保存 traceback。

## Migration Plan

无需数据库迁移。部署时必须重启后端 Worker/API 以加载新的共享循环与响应字段，并重启 Web 开发/生产进程以加载阶段 UI；旧 Run 缺少 `dialogue_stage` 时按无阶段兼容。回滚代码即可恢复旧行为，现有 JSON 快照的新增字段会被旧代码忽略。

## Open Questions

无。真实模型语义质量和视觉体感由用户在本地服务重启后按走查清单验收；本 change 不调用付费模型。
