## Why

生产 Run 在 9000 token 软阈值处会因未筛选语义候选直接跳过无工具收尾，既丢失可用的已确认对话/通用解释，也把未筛选误呈现成空结果；同时，结构化输出失败后的恢复、未派发审计分类与正式 Web 的真实执行阶段仍不完整。旧 Agent 编排已退役，现在应在唯一的统一 dialogue-loop 上修复这些边界，避免生产适配器与实验台继续出现不同表现。

## What Changes

- 软阈值触发后停止新增资料动作，但允许无工具 finalizer 使用已确认对话、已授权材料与通过检查的通用文本完成安全收尾；未筛选候选始终隔离于答案和列表。
- 当任务确实依赖未筛选候选时，保存仅包含候选筛选与最终回答的最小 continuation；继续时复验 Workspace、用户权限、对象范围、候选内容和句柄后只恢复未完成步骤，不重复成功查询。
- 对 Provider 返回的 `INVALID_JSON` 外层包装增加严格、有限的确定性兼容：仅接受内层 JSON 可严格解析且完整通过 `DialogueAnswer` 与既有引用授权校验的输出；损坏 JSON 保持失败并保存 finalize-only continuation。
- 保留格式校验重试或软阈值前已通过相关检查的文本和通用知识标注，失败输出不得覆盖已确认内容；终态按真实完成程度计算。
- 保证确定性失败兜底自身始终满足回答合同；正式适配器遇到未捕获异常时保留脱敏诊断、已产生审计和安全恢复状态，并在下一轮区分明确续接与新的独立问题。
- 将 `finalize_transition` 记录为未派发并保留预算停止原因，真实模型失败继续按失败记录。
- 复用统一循环已有 activity callback，将低频、去重后的用户可见阶段写入正式 Run 的 dialogue-loop 状态快照，并通过正式 API 传给 Web；`current_step` 继续专用于 Worker 恢复检查。
- 正式 Web 以真实阶段展示轻量状态提示，覆盖组织、查询、读取和整理回答；终态、取消、刷新、切换会话及 continuation 后不保留旧阶段，并支持减少动画偏好与可访问状态播报。
- 不提高 9000/12000 输入阈值或任何模型、工具、正文、Evidence、时间与重试预算；不新增知识写入、意图/规划模型、第二套编排、移动端改动或右侧诊断面板。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `knowledge-agent-dialogue-loop-production-adapter`: 补充软阈值安全收尾、严格 `INVALID_JSON` 兼容、未筛选候选恢复、未派发审计和正式 Web 阶段展示合同。
- `knowledge-agent-run`: 将用户可见执行阶段作为独立于 Worker `current_step` 的低频可恢复状态返回，并约束终态清理。

## Impact

- 后端：`backend/evals/dialogue_loop/` 的共享收尾、输出兼容与 continuation；`backend/app/services/knowledge_agent/production_adapter.py` 的状态持久化与模型审计；正式 Run 响应组装。
- Web：`frontend/src/pages/KnowledgeAgentPage.tsx` 与正式 API 类型、相关测试；沿用现有语义色和 Lucide 动效，不改变页面布局或移动端。
- 验证：以 Run 13 的 8295/9290 投影、5 条候选及真实 `INVALID_JSON` 响应建立确定性夹具，同时覆盖硬上限、真实模型失败、空结果、权限/句柄失效、continuation 不重复查询及实验台/生产适配器一致性。
