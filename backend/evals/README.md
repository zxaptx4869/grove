# 知识 Agent 真实多轮评测

## 统一对话循环隔离实验

`evals.dialogue_loop` 是 `prototype-knowledge-agent-dialogue-loop` 的项目内命令行
实验入口，不被正式 App、API 或 Worker 导入。默认只执行无模型预检；真实固定对照
必须显式同时传入 `--compare --live`：

```bash
# 首次隐藏输入并校验后，将 demo 密码保存到当前 Workspace 的系统钥匙串
.venv/bin/python -m evals.dialogue_loop --save-demo-password

# 不再需要保存的实验密码时显式删除
.venv/bin/python -m evals.dialogue_loop --forget-demo-password

# 无模型：身份、快照、Worker、工具白名单、模型配置与预算可控性检查
.venv/bin/python -m evals.dialogue_loop --preflight

# 零模型全链路彩排：走完 6 个子进程、24 个检查点与最终报告
.venv/bin/python -m evals.dialogue_loop --rehearsal

# 第二版零模型彩排：原三组加两组表达变体，共 10 个子进程、40 个检查点
.venv/bin/python -m evals.dialogue_loop --rehearsal --suite v2

# 仅在预检通过后运行一批三组 × 四轮 × 两臂，最多 24 条用户消息
.venv/bin/python -m evals.dialogue_loop --compare --live

# 第二版真实套件已执行一批；没有新的明确批准不得再次运行
.venv/bin/python -m evals.dialogue_loop --compare --live --suite v2

# 修正评分器后只重评已保存结果，不再登录或调用模型
.venv/bin/python -m evals.dialogue_loop --regrade data/knowledge-agent-evals/dialogue-loop/<批次>/report.json
```

`--rehearsal` 仍使用真实 demo 认证、一致快照和两臂隔离副本，但用显式标记为
`pipeline_fixture` 的本地代表值替代模型与工具执行。代表值包含 `Decimal`、集合和元组，
用于在付费评测前检查子进程传输、逐轮落盘、资源汇总、脱敏和报告生成。它的模型请求必须为 0，
不评价对话语义、共享工具效果或旧流程业务链。

`dialogue-loop-v2` 保留用户原话和已展示回答，把历史工具结果重建为配对的结构化
消息，保留实际条件、状态、完整性、可信统计及列表句柄和顺序。Entry 正文和 Source
原文完整保存在程序侧结果仓，模型视图只保留有界的本轮材料；后续引用仍须重新读取并
执行当前权限与 Evidence 核验。历史缩减不调用摘要或分类模型。

完整 Grove 规则通过 Pydantic AI 的当前 `instructions` 进入每次首轮、续聊、纠正和
独立收尾请求；历史中的旧 system 会被清除，收尾指令只作追加约束。无模型测试直接
检查底层 FunctionModel 收到的 messages 和 instructions，而非只检查 Agent 配置。

第二版按 OpenAI 兼容 Provider 请求形状投影当前 instructions、实际消息及可见工具 schema，
并用 UTF-8 字节与显式协议余量做可复现长度估算。资料软阈值为 9000，
Provider 的真实单请求输入上限仍为 12000 token。达到软阈值或只剩最后一次文本请求时，
实验先退出最多 120 秒的求解阶段，再在独立的最多 15 秒窗口内派发至多一次无工具收尾；
收尾仍计入单轮和整批预算。估算值与 Provider usage
分开记录，报告按主 Agent、工具内部模型和旧链路汇总误差；未派发请求的实际 token 保持未知。
估算不是 DeepSeek tokenizer 结果，也不保证真实 token 一定低于上限。

统计在实验层拆为 `count_entries` 与 `group_entries`，二者都复用共享
`aggregate_entries` 实现。`main_types` 未指定表示全部正式记录，用户泛称“知识”不再
默认映射为内部 `knowledge` 类型。第二版真实套件和冻结预算见
[`dialogue-loop-v2-evaluation-plan.md`](dialogue-loop-v2-evaluation-plan.md)。
下一次只诊断请求组装和估算的最小清单见
[`dialogue-loop-v2-minimal-diagnostic-plan.md`](dialogue-loop-v2-minimal-diagnostic-plan.md)，
该清单仍需另行批准。

实验运行优先从按 Workspace 隔离的系统钥匙串项读取 demo 密码；没有保存或钥匙串读取失败时
才通过终端隐藏询问。保存必须使用显式命令，并在隔离副本认证成功后写入；删除也必须显式执行。
密码只在父进程内存和子进程标准输入中短暂传递，不接受命令参数或环境变量，也不写入仓库、
临时数据库或报告。Provider 与 API key 继续由应用现有配置
和密钥存储读取；报告只保存 provider/model 与密钥是否可用，不保存密钥值。

入口先用 SQLite backup 创建一致 seed，再为旧流程、新循环建立各自的 600 权限临时
数据库。子进程在导入应用数据库模块前绑定副本，并关闭全部后台 Worker；退出时临时目录
整体清理。运行前后核对九张业务表和附件文件指纹，副本只允许新增实验 Conversation、
Message、Run、Evidence 与审计，原业务库不得写入。

冻结边界为每轮文本请求 12、向量请求 4、新循环工具动作 8、不同 Entry 30、Evidence 20，
求解 120 秒及收尾 15 秒；整批文本请求 192、向量请求 64。模型请求和框架重试在底层
派发前计数，工具并发最多 2 且使用独立 AsyncSession。输入最多 48 KiB，每次输出最多
2000 token。达到上限、业务数据变化或相同基础设施异常第二次发生即停止，不补跑。
选择 `--suite v2` 时消息上限增至 40，但整批文本 192、向量 64 的硬预算不增加。

报告写入忽略目录
`backend/data/knowledge-agent-evals/dialogue-loop/<batch>/report.{md,json}`，目录权限 700、
文件权限 600。报告保留实际回答、工具状态与原始错误、模型调用、usage 可得性和耗时；
结构化失败还保留有界公开响应、工具调用参数、finish reason、错误类别和异常链，明确排除
隐藏推理并统一脱敏。缺少 usage 标记未知。自动检查只证明确定性边界，解释质量和引用是否充分
仍须逐轮人工审阅。

本工具通过运行中的 Grove HTTP API 登录既有 demo 账号、创建 Conversation、逐轮提交
消息并轮询 Worker 的实际结果。模型和密钥继续使用后端已有配置。脚本不注册账号、
不修改业务实现、不创建测试 Entry、不直接调用模型，也不把预期答案发送给 Agent。

## 运行

在 `backend` 目录执行：

```bash
.venv/bin/python -m evals.knowledge_agent_multiturn
```

密码通过终端隐藏输入，也可从 `GROVE_EVAL_PASSWORD` 读取。不将密码写在命令参数、
仓库文件或报告中。Token 只在内存中保存，结束时调用移动端登出接口。

默认连接 `http://127.0.0.1:8000`，只读核对 `backend/grove.db`；服务必须已运行且
Knowledge Agent Worker 已开启。接口身份及每个 Run 必须与核对数据库一致。
本工具仅接受本机 HTTP 服务，不能用于远程部署。

```bash
# 原始反馈重复三次，每次使用新 Conversation
.venv/bin/python -m evals.knowledge_agent_multiturn --cases original --repeat 3

# 按本次改动影响运行子集
.venv/bin/python -m evals.knowledge_agent_multiturn \
  --cases correction,type_groups,filter_change

# 修改后运行相同场景，与已有批次比较
.venv/bin/python -m evals.knowledge_agent_multiturn \
  --compare /private/tmp/grove-agent-eval/<批次>/report.json

# 评分器修正后重评已保存响应，不重新登录或调用模型
.venv/bin/python -m evals.knowledge_agent_multiturn \
  --regrade /private/tmp/grove-agent-eval/<批次>/report.json
```

完整集合为 12 段、27 轮，默认每段一次，按顺序执行。没有空项目时跳过三个依赖
空项目的场景；账号完全没有正式记录则拒绝运行。单轮默认等待 240 秒，超时提交
取消并等待终态；仍未确认取消时停止整批，不继续发送同会话消息。

## 场景与口径

- 原始总数、项目分组、补充确认，以及同义追问。
- 纠正“知识”一词、按类型分组、替换类型筛选条件。
- 最近五条方法与“第二条”的对象指代。
- 不查知识库的开放讨论、显式新话题和后续指代。
- 首轮真实歧义、补充任务后的继续追问。
- 空项目、通过范围接口切换项目、Workspace 内自然语言指定项目。

场景同时包含已有能力的衔接与目标架构尚未提供的能力。项目分组、自然语言项目
解析单独标记为能力缺口，不把这些失败一律归为模型质量回归。

“全部知识”在本评测中指全部正式 Entry，包含 knowledge、method、parameter、reminder；
数据总数覆盖当前 Workspace 的所有项目，项目分组场景明确包含零条项目。
测试时自动选择记录最多的项目与一个空项目，不硬编码 demo 项目 id 或条数。
所有预期来自运行前的 SQLite 只读快照，聚合和排序不复用被测服务的查询函数。

## 结果解释

每批保存独立 `report.json` 和可读的 `report.md`，每轮结束即写入；文件默认位于
`/private/tmp/grove-agent-eval/`，目录权限 700、报告权限 600。报告包含 demo 对话与
有界工具结果，应作为本地调试资料，不提交整份报告到仓库。

| 结果 | 含义 |
|---|---|
| `pass` | 该轮已定义的确定性检查通过，不代表所有自然语言语义已被证明正确 |
| `fail` | 统计、口径、对象、澄清、模型调用或已定义依据边界检查失败 |
| `review` | 自动检查通过，但解释内容、自然程度和指代语义仍需人工判断 |
| `blocked` | 前一轮缺少对象或解释未通过前置检查，暂未发送依赖该结果的追问 |
| `pending` | 已提交但尚未取得可评价终态，不能算作通过 |

确定性检查包括：完整统计值与筛选口径、实际项目范围、分组桶、最近记录顺序、对象范围、第二个
实际展示对象的本轮引用，以及用户“不查知识库”的工具行为边界。综合回答中的
统计事实必须实际出现在公开回答里，不能仅因内部工具执行成功而判通过。
澄清只按脚本预先定义的必要性判断；解释性追问的前一轮失败时保守标记 blocked，
不把连带失败计为新缺陷。脚本中的“补充确认”是固定输入，不宣称使用了
自适应用户模拟器。修改测试脚本时应保留固定回归集与不参与调优的变体。

每轮核对 Entry、Source、Candidate、目录、来源材料与版本等九张业务表的内容哈希；
运行中变化则停止使用旧预期，结束后再次检查。变化可能来自用户或后台任务，
不能仅凭哈希变化断言是 Agent 写入。评测会新增对话、消息、Run、工具及模型审计，
这些记录保留用于复查，不自动清除。观察到没有正式写入不等于完成恶意写入防护测试。

没有输出对象越界只说明本批公开结果通过范围检查，不等于穷尽跨 Workspace 权限测试；
权限与正式写入防护仍应由后端独立测试覆盖。

## 基线与优化

先完整运行当前版本，逐轮阅读失败原因与诊断，然后只优化有证据指向的环节。
修改后用相同数据、模型、脚本与运行配置复测。比较器会检查数据哈希、模型配置、
脚本摘要、评分器摘要和运行期间数据稳定性；后端未公开完整运行配置，特性开关仍需人工核对。
当全部记录恰好只属于一个项目时，Workspace 总数与项目总数相同仍不能证明项目过滤正确。
重评会保留原始调用批次、生成新的报告并注明评分器摘要，不覆盖原始报告。
不要把一批小样本的百分比当成总体质量结论。

报告保存模型用途、provider/model、prompt version、fallback、工具参数、结果与延迟。
已有阶段不一定返回 usage，缺少 usage 时不能给出完整 token 或费用估算。
退出码 1 表示有失败、阻塞或执行异常；评测发现产品缺陷时返回非零是正常行为。
`review` 不使退出码失败，但不意味着人工验收已经完成。

评测器自身反例测试不会调用真实模型：

```bash
.venv/bin/pytest tests/test_knowledge_agent_multiturn_eval.py
.venv/bin/ruff check evals tests/test_knowledge_agent_multiturn_eval.py
```
