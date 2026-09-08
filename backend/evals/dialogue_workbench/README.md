# 知识 Agent 实验工作台

该入口只在本机提供自由对话实验，直接复用 `evals.dialogue_loop` 的统一循环和只读工具。

- 默认地址：`http://127.0.0.1:8765/workbench`
- 真实模式从后端配置读取 Provider 和密钥，启动本身不调用模型。
- demo 密码从 macOS 钥匙串读取；回退输入使用隐藏标准输入，不写入参数、环境或记录。
- 原业务库先制作临时一致副本；子进程只连接副本并关闭 Worker。
- 脱敏对话、公开诊断和反馈保存在 `backend/data/knowledge-agent-evals/dialogue-workbench/workbench.json`。
- `--offline` 只供自动化验收，页面会明确显示“离线桩，仅验收”。
- 轮次状态区分 `completed`、`partial_completed`、`unsupported`、`denied` 和 `failed`；预算、超时或收尾校验失败会优先保留当前轮可信结果并显示确定性缺口。
- `list_project_directories` 读取真实 Project/Node 树；`children` 查询根级或直接子目录，`leaf_summary` 一次计算整树中没有直接子节点的真实叶子目录。叶子数量不是 Entry 数量或 `main_type` 分组。
- 部分完成会记录停止原因、未完成步骤和最小 continuation。运行时上下文仍只保存在当前进程；服务重启后历史对话只读，需要新建对话重新发起查询。

从仓库根目录运行 `scripts/dialogue-workbench.sh`，停止时运行
`scripts/dialogue-workbench-stop.sh`。工作台不注册到正式 App 路由。
