# 原生知识 Agent 对话 · 验证记录

> change：add-native-knowledge-agent-conversation
> 日期：2026-08-29
> 分支：codex/add-native-knowledge-agent-conversation

## 1. 后端自动化验证

- `cd backend && .venv/bin/python -m pytest -W error`：全量通过。
- `cd backend && .venv/bin/ruff check app tests`：通过。
- 覆盖：Entry 硬预算（单轮批量、恢复剩余预算）、逐 Query 审计增量、同范围 no-op、
  最近页优先分页（首页/尾页/相同时间戳/无重复遗漏）、消息页规范化 Runs、
  列表批量最近 Run（查询次数=1）、citation 快照与删除后保留、双边冲突与旧响应兼容。

## 2. 移动端自动化验证

- `cd mobile && npm test -- --runInBand`：31 个测试通过（jest 配置 forceExit，
  原因：RNTL v14 + TanStack Query 的假定时器/GC 句柄会让正常结束阶段挂起）。
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
