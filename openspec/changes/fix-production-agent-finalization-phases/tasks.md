## 1. 确定性回归基线

- [x] 1.1 用 Run 13 的 8295/9290 投影、5 条候选和成功工具事件建立共享循环失败回归，覆盖不依赖候选与依赖候选两类任务
- [x] 1.2 从 `session-20260916-130250` 固化真实 1002 字符损坏 `INVALID_JSON`，并补充内层合法包装、未知结构和非法引用对照
- [x] 1.3 为硬上限、真实 Provider 失败、未筛选与真实空结果、无工具收尾、续接不重复查询、权限变化和失效句柄补齐确定性断言
- [x] 1.4 用 Run 786→787 夹具建立跨轮已授权 Entry 首次读取失败回归，断言一次读取、零重搜/筛选与最终完成
- [x] 1.5 用 Run 793→794→795 建立跨正式 Run 回归，复现 13 块兜底校验异常，并断言失败后新问项目数量只调用 `list_projects`
- [x] 1.6 用 Run 801→802 建立跨正式 Run 候选续接回归，覆盖快照落库、新建状态、继续成功、无重复资料调用及新问题隔离
- [x] 1.7 覆盖候选续接的权限撤回、范围切换、对象删除、Entry/Source 指纹变化和恢复材料缺失
- [x] 1.8 用基线 Run 815→818、822→824 和会话 301 Run 806 建立正式跨 Run 回归，检查实际模型 messages/instructions 包含正确 Entry、前轮分析、上一版候选与用户决定
- [x] 1.9 覆盖连续改写不回退原 Entry、失败续接稿件/缺口配对、明确新问题隔离，以及权限、范围、Entry/Source 材料变化拒绝复用

## 2. 共享收尾与恢复

- [x] 2.1 在输出校验重试前只保留通过内容边界的文本与通用知识标注，隔离未授权结构块
- [x] 2.2 让软阈值统一进入无工具 finalizer，并按真实结果区分完成、部分完成和未执行
- [x] 2.3 实现 `relevance_selection` 最小 continuation、恢复前 Workspace/权限/范围/对象/指纹复验及成功查询复用
- [x] 2.4 实现严格 `INVALID_JSON` 解包兼容，损坏内层保持 finalize-only 恢复且不增加重试
- [x] 2.5 将 `finalize_transition` 记录为 `not_dispatched`，并回归真实模型失败仍为 `model_call_failed`
- [x] 2.6 恢复已授权 Entry 的发现集与指纹，在读取前复验 Workspace/权限/项目/对象/指纹，并使后续成功读取消解临时拒绝终态
- [x] 2.7 有界化确定性失败输出，异常边界保存脱敏诊断、已有审计与安全恢复状态，并区分明确续接和新的独立问题
- [x] 2.8 在候选 finalize-only continuation 中保存最小编辑对象定位信息，完成 Workspace/身份/项目/权限/对象/Entry 与 Source 指纹复验后再重建 `editing_context`
- [x] 2.9 对“只改语气”候选交付对齐提示与校验，保留原始事实关系、数量维度和不确定性，不用固定章节或主题特判
- [x] 2.10 候选任务失败摘要只展示当前候选、准确缺口和有效恢复方式，不重放历史列表、无关记录或重复正文
- [x] 2.11 在 production adapter 快照中有界保存已有 Entry 的对象、分析、最新安全候选和用户决定，经现有数据库安全复验后才激活
- [x] 2.12 让候选 finalizer 使用已绑定的前轮分析，连续语气/精简改写以上一版候选为基准，并成对保存最新安全稿与实际缺口
- [x] 2.13 让“抛开知识库”的短追问可选择已展示正文作为讨论对象，保持资料工具禁用、来源边界和新任务隔离

## 3. 正式阶段传播与 Web

- [x] 3.1 将去重后的 activity callback 阶段写入现有 Run 快照并通过 `dialogue_stage` 返回，保持 `current_step=dialogue_loop`
- [x] 3.2 在终态、异常和取消路径关闭阶段发布并清空活动阶段，验证刷新和 continuation 不残留旧状态
- [x] 3.3 正式 Web 按真实阶段显示轻量提示，补齐终态停止、会话切换、未知阶段回退、`aria-live` 与减少动画偏好测试

## 4. 跨入口验证与收尾

- [x] 4.1 用相同状态、历史、模型响应夹具验证实验台共享循环与 production adapter 的块、终态、continuation 和审计一致
- [x] 4.2 运行相关后端测试、ruff、Web 测试/lint/build 和 `openspec validate --all --strict`，记录基线失败与实际结果
- [x] 4.3 核对冻结预算常量与无付费模型调用，更新任务状态并形成重启说明和人工语义/视觉走查清单
- [x] 4.4 运行相关后端测试、全量 Ruff、OpenSpec 严格校验和 `git diff --check`，记录自动化与待人工语义验收边界
- [x] 4.5 运行 Run 801→802 相关后端测试、Ruff、OpenSpec 严格校验与 `git diff --check`，保留跨轮读取及 13-block 回归并记录待人工语义验收
- [x] 4.6 运行候选协作链受影响后端测试、Ruff、OpenSpec 严格校验和 `git diff --check`，保留跨轮读取、候选隔离、13-block 与安全复验回归
- [x] 4.7 确认运行服务与当前提交对应后，限额复测 `collaboration_a`、`collaboration_b`、相关保留能力及单独标识的 Run 806 原始短问法，逐轮完成语义审阅并保留前后报告

## 5. 验证记录

- 后端相关测试：316 个通过；覆盖实验台、正式适配器、API 与 Worker。
- Web：149 个测试通过，生产构建通过；ESLint 0 错误，保留两个不在本次范围内的既有 Hook dependency 警告。
- 静态与规格：后端全量 Ruff 通过，`openspec validate --all --strict` 为 64 项通过、0 失败。
- 预算与模型：9000/12000、模型、工具、正文、Evidence 和时间预算均未提高；全部模型回归使用本地 `FunctionModel`，未调用付费真实模型。
- 人工验收：自动化不替代真实语义与登录后视觉走查；按交付说明重启后执行 Run 13、continuation、终态阶段清理和减少动画检查。
- 2026-09-17 跨轮 Entry 追加回归：相关后端套件 374 个通过，全量 Ruff 通过；Run 786→787 夹具确认首次仅一次 `read_entries`、零重搜/筛选且最终 `completed`，并覆盖刷新恢复、候选隔离、权限撤回、跨 Workspace、项目切换、Entry 删除和指纹变化。
- 2026-09-17 Run 794 异常恢复追加回归：274 个相关后端测试通过，全量 Ruff 通过，OpenSpec 严格校验 64 项通过，`git diff --check` 通过。Run 793→794→795 正式落库夹具确认 13 块失败摘要被稳定限制为 12 块，失败现场保留脱敏诊断、工具/模型审计和 continuation；新问“我有几个项目”仅调用一次 `list_projects` 并完成，显式“继续”仍恢复原 continuation。全部使用本地 `FunctionModel`，真实语义验收仍待人工执行。
- 2026-09-17 Run 801→802 候选续接追加回归：585 个知识 Agent 与实验台测试通过；正式 production adapter 夹具经数据库快照、新 `LoopState` 及“继续”确认仅调用一次无工具 finalizer、无重复搜索/Entry/Source/Evidence 调用并交付候选。真实 Run 801 候选文本已固化为夹具，“20cm 防倒灌空间”改成“20 公分高度”会被语义校验拒绝，10A 与两处 20cm 的数量事实也必须完整保留。共享复验覆盖 Workspace/权限/项目范围/对象及 Entry/Source 指纹变化，候选失败摘要不再重放旧列表与重复正文。全量 Ruff 检查、OpenSpec 严格校验 64 项和 `git diff --check` 通过；全部模型夹具使用本地 `FunctionModel`，未重启服务，真实语义验收仍待人工执行。
- 2026-09-17 候选协作链追加回归：`test_knowledge_agent_dialogue_loop.py` 与 `test_knowledge_agent_production_adapter.py` 全部通过。正式四轮夹具经 Run 快照落库和新 `LoopState` 恢复，确认候选 finalizer 的真实 messages/instructions 包含已复验 Entry、前轮模型分析、用户决定及上一版候选；显式 `new_topic` 不注入旧对象。“抛开知识库”只从已展示正文按位置绑定对象并复验权限与 Entry/Source 指纹，不派发搜索、Entry/Source 读取或 Evidence。连续改写以上一版候选为确定性基准；安全失败稿与同次缺口成对保存，含写入声明的输出不会替换上一安全稿。全量后端 Ruff、OpenSpec 严格校验 64 项及 `git diff --check` 通过；真实 DeepSeek 复测与用户语义验收仍待完成。
- 2026-09-17 DeepSeek 复测：本地服务由当前工作区启动，批次报告记录 commit `b5d0c64` 及受影响源码哈希；服务端未公开 commit，故运行版本仍标记为需手工核对。零模型 preflight 通过后执行 `retained_read`、`collaboration_a`、`collaboration_b` 和独立的 `short_anchored_discussion`，计划 20 轮、实际发送 18 轮，模型审计 58 条、真实派发 51 次，usage 为 input 268272、output 10638、cache read 221312，fallback 为 0。Codex 逐轮审阅后语义 9 pass、5 fail、1 not covered，4 段整段均未通过：B 链的分析与候选生成从基线失败改善为通过；A 链候选仍未落实前轮分析且继续无进展；B 语气轮完整保留内容但没有实质变得简短自然；跨轮读取 Run 830 仍 partial，新增原始短问法因 Run 845 前置读取失败未发送。原始及 reviewed 报告保存于 `backend/data/knowledge-agent-evals/formal-api/20260917T112724Z-df6818/`（本地忽略目录）。未为追求绿色补跑，用户最终语义验收仍待完成。
- 2026-09-17 复测证据追加修复：Run 833 快照已保存完整分析，但 Run 834 对同一 Entry 再次按结果位置建立编辑对象时覆盖了原 `editing_context`，导致分析、候选和用户决定丢失。现改为同一已复验 Entry 只刷新对象与指纹，保留已有协作上下文；不同对象仍重新建立任务。相关正式适配器与共享循环测试通过，全量后端 Ruff、OpenSpec 严格校验 64 项及 `git diff --check` 通过。
- 2026-09-17 有界补跑：在提交 `f94b417` 上仅复测 `collaboration_a`、`collaboration_b`，计划 14 轮、实际发送 5 轮；模型审计 19 条、真实派发 16 次，usage 为 input 86374、output 2541、cache read 77440，fallback 为 0。A 链首轮未展示固定目标 Entry，B 链正文轮未直接读取上轮对象且重复搜索后失败，后续候选、语气和 continuation 轮均按固定规则未发送，因此该批不能证明候选协作链已通过真实语义验收。原始及 reviewed 报告保存于 `backend/data/knowledge-agent-evals/formal-api/20260917T113606Z-846f1d/`（本地忽略目录）。两批累计实际发送 23 条用户消息，未继续补跑；原始短问法和修复后的完整候选链仍待用户验收，当前 change 不归档。
