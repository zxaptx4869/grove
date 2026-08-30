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
