## 1. 骨架与数据模型

- [x] 1.1 新增 Alembic 迁移，创建 `directory_drafts` 与 `directory_draft_nodes` 表
- [x] 1.2 新增 Directory Draft 模型与状态/动作常量（drafting / awaiting_input / pending_confirm / confirmed / discarded；clarify / generate）
- [x] 1.3 新增草稿、草稿节点与澄清问题的 Pydantic schema

验收：`cd backend && .venv/bin/alembic upgrade head && .venv/bin/ruff check .`

## 2. Directory Agent

- [x] 2.1 新增 `agents/directory.py`：澄清问题、候选树草稿输出与 `run_directory_clarify` / `run_directory_draft`
- [x] 2.2 Agent 输入组装：项目说明 + Project Context 快照（公共接口）+ 用户答案
- [x] 2.3 无密钥/离线确定性兜底候选树
- [x] 2.4 生成来源记录（provider / model / is_fallback），降级日志告警

验收：`cd backend && .venv/bin/pytest -q && .venv/bin/ruff check .`

## 3. 起草服务与 API

- [x] 3.1 新增 `services/directory_draft.py`：创建/复用/读取活跃草稿
- [x] 3.2 澄清答案提交与批次计数（上限 2，超限强制生成）
- [x] 3.3 候选树写入草稿节点与内联编辑（PATCH 全量替换）
- [x] 3.4 `apply`：树校验（parent 引用、无环、名称长度、节点上限 200）+ 原子创建正式节点 + 标记 confirmed + 触发 `directory_changed` 刷新
- [x] 3.5 `discard` / 重试与 Workspace/Project 越权校验
- [x] 3.6 后端测试：澄清流程、候选树生成、内联编辑、应用成功/失败回滚、越权

验收：`cd backend && .venv/bin/pytest -q && .venv/bin/ruff check .`

## 4. 前端目录共创工作区

- [x] 4.1 扩展 `lib/api.ts`：草稿、澄清问题、草稿节点类型与 API 方法
- [x] 4.2 新增目录共创工作区组件：问卷澄清（选项 + 自由输入，一次提交）、候选树、内联编辑、应用确认
- [x] 4.3 替换 `ProjectPage` 占位弹层，接入空目录与知识空间页头入口
- [x] 4.4 前端测试：问卷澄清、候选树编辑与应用确认

验收：`cd frontend && npm run test:run && npm run build`

## 5. 验证与收尾

- [x] 5.1 运行 `openspec validate --all --strict`
- [x] 5.2 运行后端测试与静态检查
- [x] 5.3 运行前端测试与构建
- [ ] 5.4 手动走查目录共创全流程（澄清 → 候选树 → 对话调整 → 内联编辑 → 应用）

## 6. 对话调整草稿

- [x] 6.1 新增 Alembic 迁移：`directory_draft_messages` 表与 `directory_drafts.conversation_rounds`
- [x] 6.2 模型与 schema：消息模型、`DraftOut.messages`、`DraftMessageOut`
- [x] 6.3 Agent：`run_directory_refine`（回复文字 + 可选新树），离线只回文字
- [x] 6.4 服务：`submit_draft_message`（追加消息、轮数上限 30、返回树自动替换节点）
- [x] 6.5 API：`POST .../messages`，草稿响应带消息列表
- [x] 6.6 前端：候选树在左、对话区在右，消息列表与发送框，返回树自动更新
- [x] 6.7 测试：对话追加、纯讨论不改树、自动应用、轮数上限、状态限制
- [x] 6.8 起草与生成改为异步 Worker，前端轮询生成状态并显示“AI 正在生成…”提示
- [x] 6.9 问卷改为单选/复选控件，选择“其他”才展示输入框
- [x] 6.10 共创工作区由弹窗改为右抽屉布局
