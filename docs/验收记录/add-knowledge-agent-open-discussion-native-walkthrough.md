# 知识 Agent 开放讨论原生端三视口走查记录

来源 change：`add-knowledge-agent-open-discussion`（任务 8.2）
走查日期：2026-09-02

> 状态：本 change 的阶段性界面验收已完成。缺少的真实模型完成态、原生系统
> 键盘、安全区与读屏焦点验证经用户确认转为生产开启
> `KNOWLEDGE_AGENT_OPEN_DISCUSSION_ENABLED` 前的上线门槛，不阻塞本 change 归档。

载体：移动端正式实现（`mobile/`，Expo / React Native），通过
react-native-web + Chrome Headless 以 360×800、390×844、412×915
三个目标视口走查；后端为 8.1 验收实例（`grove_accept_open.db`，
端口 8022，开放讨论开关开启，进程内 Worker 开启）。

说明：本仓库当前运行环境没有可用的 iOS/Android 模拟器与真机；
因此用同一套移动端代码的 Web 渲染做确定性交互与截图走查，真机
安全区/系统键盘/读屏焦点作为剩余差异列在文末，待设备验收。

## 截图路径

- `docs/验收记录/open-discussion-walkthrough/360x800-conversation-empty.png`
- `docs/验收记录/open-discussion-walkthrough/390x844-conversation-empty.png`
- `docs/验收记录/open-discussion-walkthrough/412x915-conversation-empty.png`
- `docs/验收记录/open-discussion-walkthrough/390x844-mode-sheet.png`
- `docs/验收记录/open-discussion-walkthrough/390x844-answer-knockdown.png`
- `docs/验收记录/open-discussion-walkthrough/walk-summary.json`

## 各视口结果

| 视口 | 页面/场景 | 结果 |
|---|---|---|
| 360×800 | 登录后空知识对话 | 无横向溢出（scrollWidth=360）；空态文案、建议问题与四栏底栏完整；键盘未展开 |
| 390×844 | 登录后空知识对话 | 无横向溢出（390）；主视口布局完整 |
| 412×915 | 登录后空知识对话 | 无横向溢出（412）；内容与底栏不遮挡 |
| 390×844（共享交互） | 本次提问设置 Sheet | 出现新增「回答依据」分组：自动选择 / 仅使用我的知识库；Sheet 可关闭 |
| 390×844（共享交互） | 选择“仅使用我的知识库”后发送 | Composer 保留一次性依据 Chip；发送后后端返回可见的模型离线降级/不足结果，回答区域无横向溢出 |

## 交互与可访问性

- 输入框具备 `aria-label="对话输入"`、发送按钮 `aria-label="发送"`、
  设置按钮 `aria-label="本次提问设置"`；模式 Chip 的移除按钮带
  “移除…设置”辅助名。
- Mode Sheet 的选项使用 radio 语义与选中态；回答依据分组与
  理解上下文/回答方式/结果形式并列展示。
- 走查脚本分别在三视口收集控制台：仅登录前存在 401 资源请求
  （未登录探活/无 token 查询），登录后未发现未解释 error/warning。
- DOM 溢出检查：三视口与发送后的 `scrollWidth` 均等于视口宽度。

## 剩余差异

1. 真机/iOS+Android 模拟器走查：系统键盘、安全区、底部导航与
   Sheet 关闭后的焦点归还需在设备或模拟器上复核；本环境以 Web
   渲染近似，未覆盖系统键盘与原生读屏行为。
2. 后端无模型密钥：model-first/hybrid 的“完成态开放回答”只能以
   可见降级呈现；真实完成路径由自动化评估/组件测试覆盖，待配置
   模型密钥后再做端到端截图。
3. 截图已生成，但本会话无法人工目视复核像素级细节；建议用户打开
   上述截图核对视觉与信息层级。

## 生产开启前上线门槛

在生产环境将 `KNOWLEDGE_AGENT_OPEN_DISCUSSION_ENABLED` 设为 `true` 前，必须在
iOS 或 Android 真机/模拟器中补验 model-first/hybrid 真实模型完成态、系统键盘、
安全区、Sheet 关闭后的焦点归还与读屏行为，并将截图及结果回填本记录。补验未通过时
保持特性开关关闭。
