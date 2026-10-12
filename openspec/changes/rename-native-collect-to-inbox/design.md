## Context

已核对的事实（本 change 直接采用）：

- 原生端同一个栏目有三种叫法：底栏标签与入口页标题「收集」（`mobile/app/(tabs)/_layout.tsx`、`mobile/src/capture/components/CaptureScreen.tsx`）、提交结果覆盖层出口按钮「回到收集」（`mobile/src/capture/components/SubmitOverlay.tsx`）、读屏名称「返回收集列表」/「返回收集」（`CaptureHeader.tsx`、`SourceDetailOverlay.tsx`、`PermissionPage.tsx`）。
- Web 桌面工作台与后端规格统一用「收集箱」（`openspec/specs/source-management/spec.md`、`browser-capture/spec.md`），移动端提交结果页的说明文案也已写「到桌面工作台的收集箱核对处理进展」。
- 规格把名字写死在三处：`native-mobile-foundation` 的四栏命名、`native-source-capture` 的「回到收集」出口、`native-source-library` 的「收集栏目 / 收集入口页」表述。
- 行为面没有名称依赖：该栏目没有对外接口名、深链接或数据字段以「收集」命名，「收集箱」不参与任何接口与数据结构。

## Goals / Non-Goals

**Goals:**

- 一个名字：底栏标签、入口页标题、出口按钮、读屏名称统一为「收集箱」。
- 代码与规格同步改名，栏目的行为、状态、布局完全不改。
- 读屏名称与可见文案一致，不出现「看得见收集箱、读出来是收集」的两套口径。

**Non-Goals:**

- 不做别名兼容、术语映射或迁移层。
- 不改 Web 与后端命名（它们已是「收集箱 / Source」）。
- 不改「最近收集」区块名，也不改采集、权限、提交覆盖层与来源列表的文案结构。

## Decisions

**决策 1：以 Web 既有「收集箱」作为唯一栏目名，不新造第四个词。**
跨端同一对象同名，规格里已有 Web 口径可对齐；「收集」在移动端继续作为动作词保留（如「最近收集」「完成一次采集」），只有栏目名改。

**决策 2：保留「最近收集」区块名。**
它描述列表的新鲜度，不是栏目名，与「收集箱」不冲突；改它会牵动 `native-source-library` 的行为描述与两份原型，收益不足。

**决策 3：底栏标签由 2 字变 3 字的排版验证。**
`tabBarLabelStyle` 为 11pt、四栏等宽，390×844 下每栏约 97pt，320pt 视口下每栏 80pt，「收集箱」按 11pt 排版约 33pt，不需要改字号或换行；此项按真机走查确认（见 `tasks.md` 3.3）。

**决策 4：不改 `docs/prototypes/`。**
四栏原型与收集原型是已确认的历史产物，命名以本 change 后的主规格为准；本 change 不回头改原型文件，只在此记录该偏离。

**决策 5：辅助名称与可见文案同步改名。**
只改可见文案会让读屏继续报旧栏目名；辅助名称为读屏而设，与可见文案同口径。

## Risks / Migration

- 无数据、接口与配置迁移；回滚即回退文案与规格同步。
- 唯一排版风险是 3 字标签在窄视口下的显示，已放入真机走查项；若走查发现截断，按「不换行、不缩小字号」的顺序优先检查标签间距，而不是回退命名。
