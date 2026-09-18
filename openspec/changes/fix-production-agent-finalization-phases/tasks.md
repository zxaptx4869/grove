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

## 6. 已有 Entry 对象与讨论链一致性修复

- [x] 6.1 建立真实 production adapter + `run_turn` 失败回归，覆盖批量读取、逐条打开、合法保序单项读取和实际模型 messages/instructions，不 monkeypatch `run_turn` 或手工预置 discussion
- [x] 6.2 统一 `read_entries` 与 `open_list_item` 的正文结果构造、对象身份、校验引用和父展示位置，并保留列表发现与正文读取区别
- [x] 6.3 允许同一已授权展示集合的合法保序子集读取，逐项复验 Workspace、权限、范围、存在性和指纹，并核对下游顺序与 continuation 假设
- [x] 6.4 让普通直接回答与无工具 finalizer 的明确 Entry 分析跨 Run 保存并进入候选输入，覆盖 `auto` 模式对象切换、独立问题和歧义澄清
- [x] 6.5 分离有界历史结果与本轮活动材料，保留最近实际展示集合及必要子项，失败摘要不重放无关历史材料
- [x] 6.6 运行对象与讨论链相关测试、Ruff、`git diff --check`，记录结果并完成本地阶段提交

## 7. 候选与恢复链一致性修复

- [x] 7.1 建立候选纠错、上一版表达改写、连续两次恢复和持久化稿件/缺口配对的失败回归，并检查 finalizer 实际输入
- [x] 7.2 集中维护最新安全候选与对应缺口，使运行状态、编辑上下文和 continuation 原子同步；不安全输出保留上一安全版本
- [x] 7.3 连续出现同一稿件与同一缺口时返回准确无进展说明，不增加重试、预算、通用评分器或模型阶段
- [x] 7.4 调整候选 finalizer 的内容基准：纠错/补充允许不同于原 Entry，只改表达以上一版候选为基准；消除固定来源词语误拦但继续拒绝正文错误归属
- [x] 7.5 回归权限撤回、范围变化、对象删除、Entry/Source 指纹变化、13-block、统计、搜索、正文读取和无知识库讨论
- [x] 7.6 运行候选与恢复链相关测试、全量 Ruff、OpenSpec 全库严格校验和 `git diff --check`，记录结果并完成本地阶段提交

## 8. 有限真实复测与交付

- [ ] 8.1 核对正式服务实际加载的代码版本，在最多两批、累计不超过 24 条用户消息和现有停止阈值内复测多正文短问、分析后候选、上一版改写、continuation、换话题及保留能力
- [ ] 8.2 保存不覆盖历史的原始报告和逐轮人工语义审阅；前置失败、未执行和未自然触发 continuation 均按实际记录
- [x] 8.3 将完整实施、自动化验证、真实 Run、未覆盖项、风险与回退依据写入本地讨论文档，区分已修好、仍失败和待用户验收

## 9. 本次一致性修复验证记录

- 2026-09-17 对象与讨论链：先以两个失败回归确认完整列表相等校验会拒绝合法子集、连续逐条打开后父列表“第一条”无法绑定；修复后 `test_knowledge_agent_dialogue_loop.py` 与 `test_knowledge_agent_production_adapter.py` 全部通过。新增正式 production adapter 六轮 `FunctionModel` 夹具，不替换 `run_turn`，覆盖结构化列表后批量正文读取、同一父集合逐条打开三项、普通直接分析通过 Agent 选择的 `discussion_entry_id` 持久化、候选 finalizer 实际输入包含 Entry 正文与分析、`auto` 模式切换第二条以及独立问题不覆盖 discussion。恢复后的历史 records 不再自动进入 `current_handles`，快照按最近两个用户可见 Entry 展示组保留父集合与必要子项；13-block 回归改为由当前失败任务生成 11 个材料，继续验证 12 块上限而不依赖历史材料重放。相关 Ruff 与 `git diff --check` 通过。
- 2026-09-17 候选与恢复链：先以失败回归确认自然表达会被固定来源词语校验误拦、正文来源冒充可被尾部免责声明掩盖、continuation 仍读取旧稿旧缺口且可重复空转。修复后共享循环和 production adapter 两个完整测试文件通过；程序统一附加未写入与模型判断不代表 Source 原文的确定事实，同时正文正向归属仍拒绝。最新安全稿及同次缺口通过同一函数同步到运行状态、`editing_context` 和 candidate continuation；不安全输出保留上一安全对，连续两次相同稿件与缺口返回 `candidate_recovery_no_progress` 并停止自动续接。纠错/补充提示允许候选不同于原 Entry，只改表达严格以上一版候选为事实、数量维度和不确定性基准。未增加模型阶段、预算、重试、持久化字段或通用评分器。
- 2026-09-17 跨入口兼容复验：知识 Agent 与实验台相关 618 项测试通过。保留实验台既有 `preserve_editing_draft` 调用入口，但内部只委托统一候选/缺口同步函数；程序来源尾注按 `Source/来源 + 原文` 结构去重，不再要求模型命中固定否定措辞，已有自然边界不重复追加，正文正向来源冒充仍拒绝。后端全量 Ruff、OpenSpec 严格校验 64 项及 `git diff --check` 通过。
- 2026-09-17 本次真实复测未执行：本机 `127.0.0.1:8000` 无监听进程，未发现 Grove API/Worker；按“不主动重启服务”边界没有启动服务。零模型正式评测 preflight 未发起模型请求，但在访问 API 前因非交互环境没有取得已保存 demo 凭据而退出。本次新增批次、会话、Run、用户消息和模型调用均为 0，旧报告未覆盖或冒充新证据；8.1、8.2 保持未完成。完整实施与验收记录已保存到本地忽略文档 `docs/discussions/知识Agent一致性修复实施与验收-2026-09-17.md`。

## 10. 剩余一致性问题回归与实现

- [x] 10.1 建立正式 production adapter + `run_turn` 回归，复现“已交付列表 A → 未交付内部列表 B → 第二条仍指 A”，并验证 B 交付后才更新位置参照；分别覆盖批量读取和逐条打开
- [x] 10.2 让最终 blocks 的实际引用确认跨 Run 展示顺序，内部 `displayable` 结果不再静默替换位置参照，同时保留歧义澄清和既有安全复验
- [x] 10.3 保留同次筛选的 `indirect` 分类集合，用户明确请求时通过现有工具合同激活并重新安全复验；默认仍只展示直接相关标题且不自动读正文
- [x] 10.4 建立 Run 874 原始否定声明及转折、新主语、独立句、引述、真实正面写入对照，修正局部否定作用域而不关闭安全校验
- [x] 10.5 让普通回答与 finalizer 共用 discussion 保存入口，补齐无预绑定 `editing_context` 但明确返回 `discussion_entry_id` 的跨 Run 分析保存和候选输入
- [x] 10.6 对同父集合、同 Entry 集合、同材料指纹的正文副本保留最新句柄；缺少指纹、指纹变化、父集合不同或 continuation 当前句柄均不合并
- [x] 10.7 回归候选同步、连续 continuation、换话题、统计、搜索、正文读取、权限/范围/对象/指纹失效及原有标题列表体验，运行相关测试、全量 Ruff、OpenSpec 严格校验和 `git diff --check`

## 11. 有限真实复测与本地交付

- [x] 11.1 在不启动或重启服务的前提下核对正式服务版本；可用时以最多一批、12 条消息复测四项问题及标题列表体验，保留原始报告和逐轮语义审阅
- [x] 11.2 分段完成本地提交，将实现、自动化、真实 Run、未覆盖项、风险与回退依据写入本地讨论文档，等待用户最终语义验收且不归档 change

## 12. 剩余一致性修复验证记录

- 2026-09-18 位置与间接集合：正式 production adapter 五轮 `FunctionModel` 夹具经真实 `run_turn`、快照保存/恢复与 `open_list_item`，确认已交付列表 A 后内部生成但未交付的不同顺序 B 不进入下一轮位置线索，“第二条”仍打开 A 的第二项；B 进入最终 blocks 后，同样追问改为打开 B 的第二项。批量读取与逐条打开既有独立路径继续通过。`select_relevant_entries` 在同次 direct 结果内有界保存 indirect 分类，默认工具返回和最终列表不含其标题或正文；用户明确要求时用同一工具的 `relevance_scope=indirect` 分支激活，先重新复验 Workspace、权限、项目范围、对象和发现指纹，失效时不生成展示句柄且不重新搜索。
- 2026-09-18 finalizer 与写入边界：正式 adapter 六轮夹具由求解阶段触发 `FinalizeRequired`，无预绑定 `editing_context` 的 finalizer 返回 `discussion_entry_id` 后通过统一入口保存分析，下一 Run 候选实际模型消息包含该分析。Run 874 原句“不代表它已经过官方确认或已写入正式记录”通过局部否定校验；转折、新主语、独立句、引述及真实正面写入声称继续拒绝。未新增模型阶段、提示词路由、语义裁判、数据库字段或第二套讨论状态。
- 2026-09-18 有界副本收敛：同父集合、相同 Entry 集合且校验指纹完全相同的重复正文只在快照窗口保留最新句柄；指纹不同的版本同时保留，缺少指纹时不去重。父列表、最终回答引用和 continuation 当前材料仍由原合同保存。
- 自动化：全部 `test_knowledge_agent*.py` 与 `test_dialogue_workbench*.py` 通过；额外的读工具、API 与 Worker 受影响回归通过。后端全量 Ruff、OpenSpec 全库严格校验 64 项及 `git diff --check` 通过。测试串行使用共享 SQLite；一次并行尝试因两个 pytest 进程争用建表产生 `disk I/O error`，改为串行后全部通过，不计为业务失败。
- 真实复测：现有 `uvicorn --reload` 子进程启动于 2026-09-18 11:39:44，晚于业务源码最后修改时间，可确认自动 reload 后的代码版本；没有启动或重启服务。零模型 preflight 在模型请求前因非交互环境没有取得已保存 demo 凭据而退出，本轮新批次、会话、Run、用户消息和模型调用均为 0，没有原始报告或逐轮语义结果可保存。该项按环境阻断完成核对，但四项真实 DeepSeek 语义路径仍待用户验收，不能据自动化宣称整个 change 完成。
