# 原生知识 Agent 对话 · 验证记录

> change：add-native-knowledge-agent-conversation
> 日期：2026-08-29
> 分支：codex/add-native-knowledge-agent-conversation

## 0. 2026-08-29 生产测试修正

- 调查不再按首条搜索结果立即读取 Source。每轮先完成所有合法搜索，按 Query 轮转保留候选，再按稳定轮转选择 Entry 与 Source；单 Query、单 Entry 受公平配额约束。同 Entry + 同 Source 或等价规范化 quote 不重复纳入 Evidence 账本；不同 Entry/Source 的冲突双方不被普通去重合并。
- Run 42～46 的共同症状是 12 条预算被首条 Query、重复 Source/quote 消耗，而不是“12 条本身一定不够”。优化后默认仍保持 12：定向调查/Runner 回归证明多 Query 轮转、硬上限与终态引用仍成立，尚无新的真实 Run 数据证明分配消除浪费后仍需上调。后续真机/生产验证应记录实际引用数、跨 Query 覆盖与 gaps 后再重估。
- `answer.status` 由后端最终引用校验和结构化核心覆盖评估产生：有效核心回答为 completed；有用引用但明确缺口/部分引用失效为 partial；无足够核心 Evidence 为 insufficient。Run 执行状态和 stop_reason 不再重分类回答状态。终态 coverage/gaps/conflicts 只取最终有效 citation，不再复用控制器搜索前计划。
- 回答模型 prompt 要求正文首句直接回答，并把状态、范围、来源、预算、轮次、停止原因和 coverage/gaps 留给结构化卡片。原生端已删除 insufficient → partial 的自行改写。
- Android 继续由 `softwareKeyboardLayoutMode=resize` 负责可用高度，删除完整 keyboardHeight padding 与 LayoutAnimation；iOS 通过 KeyboardAvoidingView + Safe Area 避让。消息区底部预留改为动态 Composer/Safe Area 空间（96px + inset），不再保留 154px 固定值。
- Bottom Sheet 统一使用 Sheet 内 ScrollView；draft 范围保存 projectName；轮询直接拿到终态会覆盖旧 processing Run；取消失败在过程卡持久显示并可重试；partial/fallback/failed/cancelled 均保留重新提问或恢复入口。Jest 已移除 forceExit，并用 fake timer 清理和 QueryClient cancel/clear 修复真实测试句柄。

## 0.1 2026-08-29 审查回归修复

- Evidence 候选仅在 `ledger.add_evidence` 成功后消耗 Query/Entry 配额。不可引用、重复 Source 或等价 quote 被拒绝后，按同一稳定队列继续读取替补候选；定向测试验证前序不可读 Source 不会阻止后续可核验 Source 填满 1 条硬预算。
- 回答模型的 coverage/gaps 改为 `{ summary, evidence_handles }`。服务端只持久化能关联最终输出 Evidence 的条目；重复 citation handle 去重后才计算来源数。模型漏填核心/完整性评估时，带引用回答安全降为 partial，而非默认 completed。
- partial、可恢复 fallback、failed、cancelled 均显示重新提问；取消错误绑定原 `runId`，切换会话、新建草稿或提交新 Run 时清理，不能泄漏到后续活动卡。
- 组件测试清理时先 unmount、再 cancel/clear QueryClient，并等待 409 刷新完成；取消错误测试使用 fake timer 后显式清理。全量 Jest 不再产生 act 警告、不会因未释放句柄延迟退出。

## 1. 后端自动化验证

- `cd backend && .venv/bin/python -m pytest -W error`：388 项通过。
- `cd backend && .venv/bin/ruff check app tests`：通过。
- 覆盖：Entry 硬预算（单轮批量、恢复剩余预算）、逐 Query 审计增量、同范围 no-op、
  最近页优先分页（首页/尾页/相同时间戳/无重复遗漏）、消息页规范化 Runs、
  列表批量最近 Run（查询次数=1）、citation 快照与删除后保留、双边冲突与旧响应兼容。

## 2. 移动端自动化验证

- `cd mobile && npm test -- --runInBand`：45 个测试通过；Jest 不再配置 `forceExit`，无 act 警告或延迟退出。测试 QueryClient 在清理时先卸载组件，再取消查询并清空 cache；轮询和取消错误测试使用 fake timer 后显式清理。
- `cd mobile && npm run lint`：通过。
- `cd mobile && npm run typecheck`：通过。
- `npx expo export --platform ios`：成功（Hermes bundle）。
- `npx expo export --platform android`：成功（Hermes bundle）。
- 测试覆盖：API snake_case→camelCase 归一化、最近页合并去重、draft 懒创建、
  幂等键复用、409 恢复、模式重置、AppState 轮询/停止/恢复、取消、
  五种回答状态、冲突双边、引用 Sheet、历史/范围/模式 Sheet、空态与失败重试。

## 3. 真实 Bearer Session API 走查（127.0.0.1:8898）

脚本：`/private/tmp/grove_api_walkthrough.py`、`/private/tmp/grove_citation_walkthrough.py`
（仅本地验证，不提交）。

- 注册/登录：201 / 200。
- 创建 Conversation：201；列表带 `recent_run_*` 摘要。
- 范围 PATCH 到项目：200；同范围 PATCH：200 且消息数不变（no-op）。
- 提交问题：201；同一 `client_message_id` 重放：200 且返回同一 Run。
- 活动 Run 期间再提交：409。
- Run 轮询到终态：离线确定性模型回退为 `partial`/`failed` 且 `fallback_summary`
  可识别（无密钥环境的可观测降级，非静默）。
- 取消：POST cancel 返回 200 / cancelled。
- 最近消息页：`items` 正序、`runs` 去重携带关联 Run。
- 游标向前分页：`?limit=2` 返回最近一页且 `next_cursor` 存在。
- citation/conflict 走查：`project_id/project_name/node_path` 快照正确；
  删除当前 Entry/Source 后历史快照仍可展示；冲突 `citation_a/citation_b`
  双侧完整可展示。
- 全程未出现非预期 404。

## 4. 视觉对照（Web 预览 + 原型基准）

> 本机没有 Xcode（仅 CommandLineTools）与 Android SDK/模拟器，无法执行原生
> 模拟器/真机截图与真实系统键盘走查。以下为 Expo Web（react-native-web）
> 预览 + 无头 Chrome 的布局/像素检查，作为原生验收前的补充证据；原生侧缺口
> 见第 6 节。

- 截图目录：`validation/screenshots/`。
  - `draft-390x844.png` / `draft-360x800.png` / `draft-412x915.png`：空对话首页。
  - `history-390x844.png` / `history-360x800.png` / `history-412x915.png`：
    有历史消息的对话（含知识不足卡、降级说明、完成回答卡、调查摘要、引用来源条）。
  - `proto-390,844.png` / `proto-360,800.png` / `proto-412,915.png`：原型基准。
- 布局检查（CDP 测量）：三个目标视口下 `scrollWidth == innerWidth`，
  无横向滚动；root 宽度与视口一致。
- 像素检查：草稿页背景采样 `#F7F8F7` 与主题令牌一致；顶栏为表面白；
  品牌绿（发送按钮/品牌标记）存在；历史页中知识不足卡（`#FFF5DF`）渲染在位。
- 视觉基线（令牌、字号、间距、卡片/Sheet/Composer 几何）已按原型 CSS 提取并写入
  `design.md`；React Native 字重映射（430/650/680/720/750 → 400/600/700）作为
  平台差异记录在 design.md 有意偏离中。

## 5. OpenSpec 校验

- `openspec validate add-native-knowledge-agent-conversation --strict`：通过。
- `openspec validate --all --strict`：42 passed / 0 failed。

## 6. 未完成项与影响（本机工具链缺口）

- 缺少 Xcode（`xcode-select` 仅指向 CommandLineTools）与 Android SDK/模拟器，
  无法执行 iOS/Android 模拟器或真机走查；真实系统键盘、安全区、动态字体、
  44×44 触控、reduce-motion 的原生验收未执行。
- 影响：以上项目需要在装有 Xcode 或 Android SDK 的设备上补充走查；
  已通过 Expo bundle/export（双平台）与 Web 预览布局检查降低回归风险。
- 移动端 Web 预览不等于原生验收；不代表原生渲染的最终像素结果。
