# 知识 Agent 真实多轮评测

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
| `blocked` | 前一轮没有足够对象，未发送无依据的“第二条”追问 |
| `pending` | 已提交但尚未取得可评价终态，不能算作通过 |

确定性检查包括：完整统计值与筛选口径、分组桶、最近记录顺序、对象范围、第二个
实际展示对象的本轮引用，以及用户“不查知识库”的工具行为边界。综合回答中的
统计事实必须实际出现在公开回答里，不能仅因内部工具执行成功而判通过。
澄清只按脚本预先定义的必要性判断；脚本中的“补充确认”是固定输入，不宣称使用了
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
脚本摘要和运行期间数据稳定性；后端未公开完整运行配置，特性开关仍需人工核对。
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
