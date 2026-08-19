## 1. 骨架搭建（数据模型与规格）

- [x] 1.1 新增 Alembic 迁移：`directory_drafts` 增加 `kind`（String(16) 非空默认 `draft`）与 `target_node_id`（可空 FK → nodes.id）
- [x] 1.2 更新 `models/directory_draft.py`、`schemas/directory_draft.py`：`DraftOut` 增加 `kind`/`target_node_id`/`diff`，新增 expand 请求与差异响应模型（added/kept/removed、blocked/blocker_count）
- [x] 1.3 同步产品专题 `docs/产品蓝图/目录与知识空间.md`：记录节点拓展入口与“建议移除默认勾选（受保护除外）”决策
- [x] 1.4 验证迁移：`cd backend && .venv/bin/alembic upgrade head` 后 `openspec validate --all --strict` 通过

## 2. 后端核心实现

- [x] 2.1 新增子树 Entry 计数与受保护删除校验（`count_subtree_entries` / `assert_subtree_removable`），接入手动 `delete_node`：子树含正式 Entry 返回 409 与阻断数量；删除目标节点时把指向它的活跃 `expand` 草稿置 `discarded`
- [x] 2.2 `agents/directory.py` 新增 `run_directory_expand`：跳过澄清，输入含目标节点路径/说明、现有子树、Project Context 快照、相关 Entry（子树全部、≤40 条、每条 ≤200 字、标注截断），输出完整目标子树；离线确定性兜底；返回 GenerationMeta（provider/model/is_fallback）
- [x] 2.3 `services/directory_draft.py`：新增 expand 草稿创建/复用与覆盖重置（清节点与消息、清零轮数与澄清批次、置 kind/target）；`expansion_diff` 按规范化名称递归计算 新增/保留/建议移除 与受保护标记；`_build_expand_context` 组装 Agent 输入
- [x] 2.4 `services/directory_draft.py` 应用分流：`kind=expand` 校验目标节点存在与草稿树合法，单事务创建勾选新增节点（根级追加到目标节点子节点末尾）、删除勾选未阻断移除子树；任一失败回滚保持 `pending_confirm`
- [x] 2.5 对话调整按 kind 分支：`expand` 草稿把完整目标子树交给 `run_directory_refine`，返回新树后替换并刷新差异
- [x] 2.6 `api/directory_draft.py` 新增 `POST /directory-draft/expand {node_id}`；`GET` 响应附带差异快照；`apply` 按 kind 分流
- [x] 2.7 后端测试：新增 `test_node_expansion.py` 覆盖直接生成、差异计算、受保护移除回滚、expand 应用、覆盖重开、手动删除保护、目标节点删除作废草稿；`bash scripts/backend-test.sh` 通过

## 3. 前端实现

- [x] 3.1 `lib/api.ts`：新增 expand 接口、diff 类型（added/kept/removed、blocked/blocker_count）与 `DirectoryDraftPayload` 扩展字段
- [x] 3.2 `NodeTree.tsx` 节点更多操作菜单新增「AI 拓展」项，`NodeTreeCallbacks` 增加 `onExpand`
- [x] 3.3 `ProjectPage.tsx`：内容区（选中节点时）增加「AI 拓展」按钮；已有活跃草稿时先弹覆盖确认；手动删除弹窗在受保护时展示阻断数量与原因
- [x] 3.4 `DirectoryDraftDialog.tsx` 支持 `mode="expand"` 与目标节点：标题“AI 拓展节点「xxx」”、打开时调用 expand 接口并轮询、差异面板（新增默认勾选可取消、保留仅展示、建议移除默认勾选且受保护禁用并显示“含 N 条正式知识，不可移除”）、受保护提示条、页脚统计与“应用拓展”按钮、对话区沿用双栏布局
- [x] 3.5 前端测试与构建：`bash scripts/frontend-dev-bg.sh` 手工走查 + `npm run build`（或既有测试脚本）通过

## 4. 验证与收尾

- [ ] 4.1 运行 ruff（`backend/.venv/bin/ruff check backend`）、后端与前端测试，全部通过
- [ ] 4.2 手工走查：演示项目节点拓展全流程（生成 → 差异 → 受保护提示 → 应用 → 目录刷新），并验证手动删除含 Entry 节点被拒绝、删除目标节点后草稿作废
- [ ] 4.3 运行 `openspec validate --all --strict` 通过
- [ ] 4.4 执行 `openspec archive add-directory-agent-node-expansion` 同步主规格，确认无遗留 active change 后本地提交
