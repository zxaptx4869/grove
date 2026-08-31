# 实施验证记录：add-knowledge-agent-entry-revision

## 1. 开工基线（任务 1.1-1.6）

### 1.1 阅读范围

- 已阅读仓库根 AGENTS.md，遵循 OpenSpec 工作流与本地提交/推送边界。
- 已完整遵循 openspec-apply-change 与 grove-ui-conventions 两个 skill。
- 已通读 proposal.md、design.md、tasks.md 与 specs/ 下 6 份 delta 规格。
- 已读取产品蓝图索引与三份相关专题。
- 已读取相关主规格 8 份。
- 已阅读移动原型 grove-mobile-agent-prototype.html 的关键片段。

### 1.2 分支与前置修复状态

当前分支开工时已包含草稿 Evidence 范围、空白草稿字段、草稿取消失败展示、
空正文要点修复；main 上另有全部要点丢弃降级与确认回执路由状态两个修复提交，
已按用户要求安全合入当前分支（merge commit 849ccde）。

### 1.3 自动化基线（开工前）

| 检查项 | 结果 |
|---|---|
| 后端 pytest backend/tests | 440 项收集，全部通过 |
| 后端 ruff check | 通过 |
| 移动端 Jest --runInBand | 10 套件 / 74 项，全部通过 |
| 移动端 lint / typecheck | 通过 |
| openspec validate --all --strict | 47 项通过 |

### 1.4 移动原型视觉基线（本 change 采用范围）

对应页面：grove-mobile-agent-prototype.html 的可编辑知识草稿、diffOverlay、
确认修改 Sheet、执行回执与撤销 Sheet。

主验收视口：390x844；扩展视口：360x800、412x915。

全局令牌（theme.ts 与原型 CSS 变量一致）：

| 令牌 | 值 |
|---|---|
| 页面背景 | F7F8F7 |
| 表面色 | FFFFFF |
| 柔和表面 | F1F4F2 |
| 边框 | DDE3DF |
| 主文字 | 17201C |
| 次要文字 | 66716B |
| 品牌绿 | 236748（软底 E8F3ED） |
| AI 紫 | 7251A5（软底 F2EDF8） |
| 已确认 | 187C72（软底 E7F5F2） |
| 风险 | 9A6419（软底 FFF5DF） |
| 错误 | B43C3C（软底 FCEDED） |

字体与排版：系统字体栈，正文 14px/行高 1.5，说明 11px，卡片标题 16px/700，
Sheet 标题 17px/700，按钮 13px/650，Badge 10px/650。

应用壳：顶栏 min-height 58px+safe-top，44px 图标区，左右 14px 内边距；
Sheet 圆角 18px、顶部把手 36x4px；全屏 overlay 底部固定 footer 加 safe-bottom。

关键组件尺寸：

| 组件 | 值 |
|---|---|
| Card | 圆角 10px、边框 1px、body padding 13px、卡片阴影 |
| Badge | min-height 21px、圆角 4px、padding 2px 6px、字体 10px |
| 按钮 | min-height 44px、圆角 8px、padding 0 13px |
| 主按钮 | 绿底白字；danger 错误软底红字；ghost 透明底 |
| 草稿输入 | 标题高 40px；正文 textarea min-height 104px、12px/19px |
| 差异块 | 圆角 9px、头部 min-height 42px |
| 回执 | 绿边、图标 34x34、行 min-height 40px |
| 编辑 Sheet | max-height 92%、滚动+底部安全区、键盘 padding 24px |

关键状态文案与元素顺序（单 Entry 裁剪后）：

1. 引用详情 Sheet：Entry 徽标、标题、项目/目录路径、核验 SOURCE 原文、
   来源元信息，之后提供「修订这条知识」动作。
2. 修订指令 Sheet：Entry 标题、项目/目录、当前摘要、非空指令输入、提交/关闭。
3. 草稿生成中：AI 标签、过程卡（可验证阶段）、取消。
4. 修订草稿卡：「可编辑知识草稿」+「AI 建议 · 待确认」、目标 Entry/项目/目录、
   变更字段摘要与来源数量、「编辑并检查」。
5. 全屏差异审阅：返回 +「审阅完整差异」、目标 Entry 与路径、按字段展示
   原内容/建议内容（未变字段折叠）、底部确认主按钮。
6. 确认 Sheet：明确将更新 1 条正式知识并追加版本、保留既有来源、
   未发生后续修改时可撤销；返回检查 / 确认执行。
7. 执行过程：校验当前版本、更新 Entry 与来源、保存版本三项可验证阶段。
8. applied 回执：「正式知识已更新」+版本、来源增量、查看 Entry/差异、撤销。
9. 撤销确认 Sheet：恢复操作前状态；审计记录不会删除；取消 / 撤销操作。
10. 版本冲突：回执保持 applied，展示知识后来发生了变化，请到版本历史处理。

长内容/键盘/安全区基线：Sheet 内独立滚动；键盘弹出后主操作可滚动可达；
safe-bottom 计入底栏与全屏 footer；触控目标不小于 44x44；
纯图标按钮提供 accessibilityLabel；状态不只依赖颜色。

有意偏离（与 design.md 一致）：不显示多对象计数；不显示重复/冲突影响对象；
执行过程收敛为三项可验证阶段；撤销存在后续版本时不可用并展示冲突说明；
修订必须从 Entry 目标动作发起，不自动识别写意图。

## 10. 全链路验证结果

### 10.1 后端全量

- `backend/.venv/bin/pytest backend/tests`：491 项收集，全部通过
  （开工基线 440 项，新增 51 项修订相关测试）。
- `backend/.venv/bin/ruff check backend/app backend/tests`：通过。

### 10.2 移动端全量

- `npm test -- --runInBand`：10 套件 / 93 项，全部通过（开工基线 74 项）。
- `npm run lint`：通过。
- `npm run typecheck`：通过。
- `npx expo export --platform ios --platform android`：iOS/Android bundle
  均导出成功（入口 bundle 3.2MB/2.9MB）。
- Expo Web 冒烟：`expo start --web` 返回 200（仅辅助，不替代真机验收）。

### 10.3 迁移

- fresh SQLite `alembic upgrade head`：成功（含本 change 新表）。
- `downgrade -1` → `upgrade head`：成功，修订表可重建，既有表保留。
- 本机无 MySQL 8 环境：MySQL 迁移/并发语义未实测，已通过
  SQLite/MySQL 兼容写法（batch_alter_table、BigInteger variant、circular FK
  分步建立）与模型测试覆盖，正式 MySQL 验收列为未验证项。

### 10.4 真实 API curl 走查（临时数据库）

在临时 SQLite 库启动真实后端（uvicorn + 进程内 Worker），记录结果：

| 步骤 | 结果 |
|---|---|
| 注册 / 项目 / 节点 / 来源 / 归档 Entry | 201 / 201 / 201 / 201 / 200 |
| 修订提交（新 client_message_id） | 201，draft=generating，target_entry_id 正确 |
| 修订提交重放（同 client_message_id） | 200，返回同一 draft_id |
| 消息页归并 | items=2、runs=1、entry_revision_drafts=1 |
| Worker 生成（无模型密钥） | draft=failed，error=“未配置文本模型密钥”，无伪草稿 |
| 编辑草稿 | 200，服务端 changed_fields 含 title/content/main_type/info_nature/applicable_condition |
| 确认（client_operation_id=wc-confirm-1） | 200，draft=applied，execution=applied，after_version=2，Entry 标题已更新 |
| Entry 版本列表 | [(2, knowledge_agent_revision, 按用户要求改写), (1, created)] |
| 撤销（wc-undo-1） | 200，draft/execution=undone，Entry 恢复到版本 1 内容 |
| 撤销重放（同 undo 键） | 200，返回同一 execution_id，不追加第二个恢复版本 |
| 第二次确认后桌面编辑 → 撤销 | 409，detail=“知识后来发生了变化，不能自动撤销；请到版本历史处理” |
| 其他用户读取/撤销草稿 | 404（不暴露存在性） |
| 未登录访问新端点 | 401 |

数据库审计快照（临时库）：

- executions：[(1, undone, before=1, after=2, added_evidence=[]),
  (2, applied, before=3, after=4, added_evidence=[])]；
- entry_versions 变更类型序列：created → knowledge_agent_revision → restored →
  knowledge_agent_revision → edited；
- entry_source_evidences 共 2 条（采用证据与既有等价，去重复用，未重复建行）。

### 10.5 设备截图与系统能力走查

- 本机无 Xcode / Android SDK / 已连接设备，无法在真实 iOS/Android 页面完成
  390×844、360×800、412×915 截图与系统键盘、安全区、动态字体、读屏实测。
- 已通过 iOS/Android Expo export 验证 bundle 可构建；通过组件测试覆盖
  44×44 触控、accessibility label、长内容滚动、Sheet 关闭与错误终态语义；
  Expo Web 冒烟返回 200（仅辅助）。
- 真实设备截图与系统能力走查列为未验证项，需用户在有模拟器/真机的环境验收。

### 10.6 规格与差异检查

- `git diff --check`：通过。
- `openspec validate add-knowledge-agent-entry-revision --strict`：valid。
- `openspec validate --all --strict`：47 项通过。

### 10.8 独立代码审查结论

重点核查项与结论：

1. 客户端不可伪造 target/Evidence/diff：修订动作只接受 source_run_id +
   target_entry_id + instruction；目标与允许 Evidence 由服务端从最终 citations
   解析并重验；diff 由服务端按 base snapshot 计算；编辑 schema 使用
   `extra="forbid"` 拒绝受保护字段。✓
2. 事务原子性：确认与撤销均在单事务内完成字段/版本/Evidence/Execution/状态
   写入，任一步异常整体回滚；工具调用记录在事务后独立提交，失败不伪装成功。✓
3. rollback 后对象状态：基线过期/Evidence 失效/无差异路径显式把 Draft 恢复为
   draft 并提交，避免停留在 confirming；undo 失败保持 applied 且可重试。✓
4. 幂等与并发：submit 按 client_message_id 重放；确认按条件 UPDATE +
   Execution.draft_id 唯一键；撤销按 undo_client_operation_id 唯一键 +
   after fingerprint/版本双重校验；并发重放返回同一对象。✓
5. 版本滚动与撤销 Evidence 精确性：撤销使用 Execution.before 快照而非可能被
   滚动清理的旧 EntryVersion；只删除 added_evidence_ids 且仍属目标 Entry 的关系。✓
6. 工作集与既有行为：entry_revision 分支不执行搜索/调查、不推进工作集；
   既有 answer/draft_candidate/桌面编辑/AI 修订/版本恢复测试全量通过。✓

审查后修复（2026-08-31 复查）：

1. 生成终态并发取消竞态：候选字段与状态改为单条条件 UPDATE（仅 generating →
   draft），不再先改内存对象再 flush，避免 autoflush 用陈旧状态覆盖并发取消；
   新增独立会话取消竞态测试。
2. 确认/撤销网络未知重试：移动端区分可重试（保留幂等键）与确定性冲突，
   Sheet 与回执只在可重试时提供「重试确认/重试撤销」，确定性 409 保持禁用并
   持久展示冲突说明；撤销冲突说明按草稿归属展示在回执上。
3. 确认失败恢复不覆写并发取消：`_restore_revision_draft_editable` 仅对
   confirming 状态生效，新增取消竞态回归测试。
4. 打开修订指令 Sheet 时关闭引用 Sheet，避免两层弹层叠放。

### 剩余风险与未验证项

- MySQL 8 迁移/并发语义未实测（本机无 MySQL）。
- 真实 iOS/Android 设备截图、系统键盘、安全区、动态字体、读屏走查未完成。
- 真实模型成功生成路径未在本机复现（无模型密钥）；已由测试内 fake agent
  确定性覆盖，并实测了无模型时的失败/重试路径。
- 撤销与「再次修订/版本恢复」竞争未做 MySQL 级并发压测；SQLite 语义已覆盖。
