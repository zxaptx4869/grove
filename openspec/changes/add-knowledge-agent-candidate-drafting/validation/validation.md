# add-knowledge-agent-candidate-drafting 实施与验收记录

日期：2026-08-30
分支：`codex/add-knowledge-agent-candidate-drafting`

## 实施范围

完成第一条低风险知识写操作纵向路径：

有有效引用的回答 → 显式点击「整理成知识」→ 创建可恢复 operation Run → 生成可编辑
Candidate Draft → 用户确认 → 创建虚拟 Source / Attachment / Extraction / pending
Candidate。全程不创建、修改、合并、移动或删除正式 Entry；普通 Composer 文本仍按只读
问答处理；不实现正式知识合并、完整差异审阅、影响对象、正式知识撤销或移动确认台。

## 真实命令与结果

### 实施前基线（任务 1.3）

```bash
cd backend && .venv/bin/python -m pytest tests/test_reader.py \
  tests/test_knowledge_agent_conversations.py tests/test_knowledge_agent_runner.py -W error
# 40 passed（tasks.md 中写为 test_knowledge_agent_runs.py，仓库实际文件名为
# test_knowledge_agent_runner.py，已在本次记录中注明）

cd mobile && npm test -- --runInBand && npm run lint && npm run typecheck
# 10 suites / 46 tests passed；lint 与 typecheck 通过
```

### 后端

```bash
cd backend && .venv/bin/python -m pytest -W error
# 425 passed in 35.69s
cd backend && .venv/bin/ruff check app tests
# All checks passed!
cd backend && .venv/bin/alembic upgrade head
# Running upgrade c4d5e6f7a8b9 -> d5e6f7a8b9c0, add knowledge candidate draft model
# downgrade/upgrade 往返由测试 test_migration_upgrade_downgrade_upgrade_and_draft_columns 覆盖
```

新增测试文件：

- `tests/test_knowledge_agent_candidate_drafts.py`：27 项（模型约束、迁移、共享创建服务、
  来源 Run/Evidence 复验、Draft 提交/执行/取消/恢复/确认幂等/隔离/路由受影响/工作集不变）；
- `tests/test_knowledge_agent_draft_api.py`：8 项（Bearer 鉴权、201/200 幂等、编辑/确认/
  重放、跨 Workspace 404、活动 Run 409、查询数量有界、旧 answer 缺省字段、桌面确认台可见）。

### 新端点 curl 验证（非 404）

本地开发服务 `http://127.0.0.1:8000`（uvicorn --reload）验证结果（未登录预期 401）：

| 端点 | 方法 | 结果 |
|---|---|---|
| `/api/knowledge-agent/conversations/1/drafts` | POST | 401 |
| `/api/knowledge-agent/drafts/1` | GET | 401 |
| `/api/knowledge-agent/drafts/1` | PATCH | 401 |
| `/api/knowledge-agent/drafts/1/cancel` | POST | 401 |
| `/api/knowledge-agent/drafts/1/confirm` | POST | 401 |

### 移动端

```bash
cd mobile && npm test -- --runInBand
# 10 suites / 68 tests passed
cd mobile && npm run lint
# 通过
cd mobile && npx tsc --noEmit
# 通过
cd mobile && npx expo export --platform ios
# ios bundles: _expo/static/js/ios/entry-*.hbc 导出成功
cd mobile && npx expo export --platform android
# android bundles: _expo/static/js/android/entry-*.hbc 导出成功
```

### OpenSpec

```bash
openspec validate add-knowledge-agent-candidate-drafting --strict
# Change 'add-knowledge-agent-candidate-drafting' is valid
openspec validate --all --strict
# Totals: 44 passed, 0 failed (44 items)
git diff --check
# 无输出（通过）
```

## 真实 Bearer Session / 服务端 Run 走查（任务 9.1 / 9.2）

以下场景由 `tests/test_knowledge_agent_draft_api.py` 与
`tests/test_knowledge_agent_candidate_drafts.py` 以真实 FastAPI 应用、真实 Bearer
Session 与真实服务端 Worker Run 覆盖：

- 项目范围回答整理：目标项目固定为会话项目，草稿 target_project_id 一致；
- Workspace 单项目预填：未传目标项目可直接提交；
- Workspace 多项目选择：未选择返回 422，选择后成功，只采用该项目的 Evidence；
- partial 只整理有依据部分：允许提交并保留有效引用；
- 无引用/未完成/取消来源回答拒绝（409）；
- 编辑草稿、取消草稿、确认草稿、confirmed 重放返回同一 Candidate；
- 未知确认结果重试复用同一 `client_operation_id`（移动端 controller 测试）；
- Evidence 失效返回 409 且 Draft 保持可编辑，不创建 Candidate；
- 历史恢复：消息页返回去重 `candidate_drafts`，重启/分页后恢复真实状态；
- 跨用户/Workspace/Conversation/project 一律 404 或 400，不暴露对象；
- 确认后只新增虚拟 Source/Attachment/Extraction/pending Candidate，Entry 数量与内容不变；
- 桌面确认台 `GET /api/sources/{id}/candidates` 可查看新 pending Candidate；
- 旧 Reader `/reader/save-candidate` 经共享创建服务保持兼容（`tests/test_reader.py` 全通过）。

## 设备验证（任务 8.1–8.4）

本机工具链检查结果：

- `xcrun simctl`：不可用（未安装 Xcode 命令行开发者工具）；
- Android SDK / adb / emulator：未安装。

因此 **未执行** iOS/Android 真机或模拟器验证，包括系统键盘开闭、多行输入增长、
Sheet 滚动与安全区、底栏隐藏/恢复、焦点归还与返回行为的原生验收；未使用 Web
伪键盘代替原生验收，也不宣称已完成设备级验收。

已完成的本机可验证部分：

- 组件测试覆盖 eligible/ineligible、单/多项目、生成、长草稿编辑、取消、确认中、
  成功回执、失败/降级与错误状态（`components.test.tsx` 12 项草稿相关断言组）；
- 44×44 触控目标：`AppButton`、操作按钮、Sheet 关闭按钮、类型 chip、取消按钮等
  主要触控目标均设置 `minHeight: 44`；纯图标按钮带 accessibilityLabel；
- 读屏：草稿卡/过程卡/回执/Sheet 控件提供 role、label、state（disabled/checked/
  expanded），状态同时使用文字 + Badge，不只依赖颜色；
- Sheet 长内容滚动：编辑 Sheet 使用 ScrollView + 键盘高度垫底 + 底部安全区，
  `keyboardShouldPersistTaps="handled"`；
- reduce-motion：组件未新增自主动画，Sheet 仅使用系统 Modal 过渡；
- iOS/Android Expo export 均成功，说明打包链路完整。

未验证项（明确记录，等待真机/模拟器环境后补验）：

1. 390×844 / 360×800 / 412×915 三视口真机截图与逐项视觉走查；
2. 系统键盘开闭与多行输入增长、焦点归还、底栏隐藏/恢复；
3. 安全区与返回行为（Android 返回键关闭 Sheet、iOS 手势返回）。

## 有意偏离与规格核对（任务 9.4）

- 不展示保留/补充/替换/合并计数；不实现「审阅完整差异」全屏页；不显示正式 Entry
  影响对象；不提供「确认合并」或撤销；
- 成功文案固定为「已创建待确认知识，尚未写入正式知识」；
- 移动确认台未接入，回执不提供伪造的「去确认台」跳转；
- 项目范围只列项目，不展示目录节点；
- 普通问答消息不因文本自动进入写分支（只有结构化 draft_candidate 动作）；
- 草稿生成/确认/取消/恢复全程记录 provider/model/fallback/error 与阶段可观测记录，
  模型不可用使用确定性 seed 并显式标记降级，无有效 Evidence 时稳定失败；
- 所有数据按 owner + Workspace 隔离，确认接口不接收客户端引用字段。

## 遗留与后续优化

设备级视觉验收（8.1–8.3 的真机部分）为本次唯一未验证项，需在具备
iOS/Android 模拟器或真机后补充走查并回填本文件。路由/关系异步化、自由文本写意图
识别、正式知识合并/修订/撤销等明确不在本 change 范围，留待后续 change。
