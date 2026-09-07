## Context

当前 `backend/evals/dialogue_loop/` 已提供第二版统一 Agent、真实只读工具、隔离快照、预算、收尾、诊断和钥匙串密码，但入口只按固定场景启动短生命周期子进程。用户需要直接体验自由对话，并在同一页面审阅真实执行过程和提交反馈。该能力仍是本地实验，不进入正式 App。

## Goals / Non-Goals

**Goals:** 交付一个单 URL 的本机桌面工作台；真实模式直接复用统一循环；身份与数据范围完全由服务端固定；刷新保留记录；取消、失败、预算和诊断可见；自动化可以显式离线运行。

**Non-Goals:** 不调整 Agent 提示词、工具选择或回答算法；不接入正式 App 路由、Worker 或数据库；不提供远程访问、多用户、知识写入、生产恢复或语义质量保证。

## Decisions

### 1. 父进程制作快照，独立子进程承载本地 FastAPI

新增 `evals.dialogue_workbench` 启动器。父进程只解析原库、读取钥匙串、建立 700 权限运行目录、用 SQLite backup 创建 600 权限副本并保存原库指纹；然后以标准输入把密码交给全新 Python 子进程，子进程环境先设置副本 `DATABASE_URL` 和全部 Worker 关闭开关，再导入应用数据库与工作台服务。退出后父进程复核原库指纹并删除数据库副本，保留脱敏记录。

这比在一个进程内清理 `get_settings` 缓存可靠，也避免把密码放进参数或环境。服务强制绑定 `127.0.0.1`；不支持 `0.0.0.0`。启动预检核验 demo、Provider、真实密钥、工具注册和上下文控制，但不调用模型。

### 2. 真实引擎只包装现有统一循环

服务启动时安装现有 instrumentation，取得后端配置的真实文本模型并构造 `build_agent(model)`。每个新对话通过实验已有 `_create_conversation` 创建副本记录，并持有自己的 `LoopState` 与 compact history；每轮复用 `_submit_turn`、`run_turn` 和 `_finish_new_run`。不复制工具或回答逻辑。

整个服务复用一个 `BudgetLedger` 与 instrumentation，并用全局异步锁串行实际生成，从而使 192 次文本、64 次向量批次预算跨对话可审计且不能靠新建对话重置。同一对话还使用客户端请求标识去重。停止操作取消对应 asyncio task；`CancelledError` 直接终止，不调用收尾，并从当前 `LoopState` 渲染已核验安全材料。

离线自动化通过依赖注入的 `WorkbenchEngine` 桩覆盖网络模型边界，响应必须标注 `offline_fixture`，不能用于真实启动或在页面冒充配置模型。

### 3. HttpOnly 本机会话与持久化边界

浏览器首次请求 bootstrap 时，服务生成随机 HttpOnly、SameSite=Strict 会话 Cookie，服务端把它绑定到已认证 demo 的 user/workspace；API 请求从不接收身份字段。会话、对话和轮次 ID 都要在服务端重新核对归属。CORS 不开放，前端静态资源与 API 同源。

`backend/data/knowledge-agent-evals/dialogue-workbench/workbench.json` 保存跨启动的脱敏公开数据，目录 700、文件 600，并用临时文件原子替换。运行时对象、模型消息、完整原文仓和数据库副本不跨进程恢复；新启动载入旧对话时标为只读和“运行上下文不可恢复”。当前进程内刷新通过同一服务端状态继续。导出复用同一 sanitize 边界，不含 Cookie、密码、密钥或 ThinkingPart。

### 4. 轮询公开阶段，不暴露思考

前端对活动轮次短轮询。统一循环在模型派发、结构化查询、Entry 读取、Evidence 读取和独立收尾等实际边界发布枚举阶段；阶段只描述可验证动作。页面不显示 token-by-token 文本，不构造“思考中”内容。轮次终态后停止轮询。

### 5. 独立 Vite 多页入口，由实验服务提供静态资源

新增 `workbench.html` 和 `src/experiments/dialogue-workbench/`，Vite 多页构建同时产出正式入口与实验入口；实验服务只把构建后的 `workbench.html` 和 assets 作为静态文件提供，不把页面注册到 `App.tsx`、正式导航或正式 API。启动脚本先构建前端，再启动后端，用户只访问一个 loopback URL。

### 6. 视觉基线与状态

- 全局令牌与字体：完全复用 `frontend/src/index.css` 的 `background/card/muted/border/brand/confirmed/risk/error`、14px 正文、现有系统中文字体、6px 基础圆角和既有阴影。
- 应用壳：全高三栏；左栏 260px，中心 `minmax(480px, 1fr)`，右栏 340px；顶层状态条 58px。主视口 1440px，扩展检查 1280/1600px；1024px 压缩为 220px / 弹性 / 300px，1023px 阻断。
- 主要组件：对话行最小 44px；用户消息最大 72% 宽；助手回答不包外层装饰卡，统计、列表和来源只在各自真实结构处使用 6px 边框容器；输入区固定在中心底部，按钮 36px；执行记录用原生可访问 `details` 默认折叠。
- 状态色不单独传达含义；所有运行、成功、提前收尾、失败、取消和只读状态都有文字与图标。动态消息、长标题、错误和 token 未知不改变三栏轨道。

移动端原型只提供对话、来源、过程和输入层级参考；桌面工作台有意改为三栏密集布局，因为本 change 的主要任务是比较回答与诊断，而不是复制原生手机壳。正式 App 导航、范围选择和“整理成知识”不在此入口出现。

## Risks / Trade-offs

- [单进程内存状态不可崩溃恢复] → 每次变化持久化公开记录；重启后旧对话只读，不声称恢复模型上下文。
- [取消发生在底层 HTTP 不可立即中断] → 取消 asyncio task 并显示请求终止中；不派发额外收尾，最终状态与已核验材料落盘。
- [构建目录可能过期] → 启动脚本固定先执行 Vite build，服务启动核对 `workbench.html` 存在。
- [本机服务仍可被本机其他进程访问] → loopback、HttpOnly 随机会话、SameSite 严格、Origin 校验和服务端固定身份共同限制；不把该方案推广到远程环境。
- [共享预算使不同对话不能并发] → 页面明确显示“单实验串行”，优先保证预算和上下文不会串线。

## Migration Plan

本 change 只新增实验目录和独立构建入口。删除启动脚本、实验包和入口文件即可回退；正式数据库无需迁移。实施与自动化完成后启动本地服务等待用户试用，不归档、推送或合并。

## Open Questions

自由聊天的真实语义效果、输入估算校准和已知 C 组类型误解仍由用户试用与后续最小诊断判断，不属于页面交付阻塞项。
