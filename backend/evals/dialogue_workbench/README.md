# 知识 Agent 实验工作台

该入口只在本机提供自由对话实验，直接复用 `evals.dialogue_loop` 的统一循环和只读工具。

- 默认地址：`http://127.0.0.1:8765/workbench`
- 真实模式从后端配置读取 Provider 和密钥，启动本身不调用模型。
- demo 密码从 macOS 钥匙串读取；回退输入使用隐藏标准输入，不写入参数、环境或记录。
- 原业务库先制作临时一致副本；子进程只连接副本并关闭 Worker。
- 脱敏对话、公开诊断和反馈保存在 `backend/data/knowledge-agent-evals/dialogue-workbench/workbench.json`。
- `--offline` 只供自动化验收，页面会明确显示“离线桩，仅验收”。

从仓库根目录运行 `scripts/dialogue-workbench.sh`，停止时运行
`scripts/dialogue-workbench-stop.sh`。工作台不注册到正式 App 路由。
