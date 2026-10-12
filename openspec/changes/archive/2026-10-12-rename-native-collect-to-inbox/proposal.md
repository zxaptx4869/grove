## Why

原生端「收集」栏目在身上带着三个名字：底栏标签与入口页标题叫「收集」，提交结果覆盖层的出口按钮叫「回到收集」，读屏名称叫「返回收集列表」；而 Web 桌面工作台与后端规格一直叫「收集箱」（`source-management`、`browser-capture` 都用「收集箱」）。同一个人在同一产品里会看到「回到收集」与「到桌面工作台的收集箱核对处理进展」两种叫法。规格里也已把这个名字写死（`native-mobile-foundation` 的四栏命名、`native-source-capture` 的「回到收集」出口），所以只改代码会让实现与规格相悖。

## What Changes

- 底栏第二栏从「收集」改为「收集箱」；收集入口页标题同步为「收集箱」。
- 提交结果覆盖层出口按钮「回到收集」改为「回到收集箱」；覆盖层内提到该出口的文案同步。
- 采集页提示「提交后可在「收集」列表里查看处理状态」改为「收集箱」；页面辅助名称（「返回收集列表」「返回收集」）同步为「收集箱」口径，保证读屏与可见文案一致。
- 保留「最近收集」（列表区块名）与「采集」「来源」等动作/对象词不变；采集页、权限页、提交覆盖层与来源列表的行为、状态和文案结构完全不变。
- 规格同步：`native-mobile-foundation`（四栏命名与栏目引用）、`native-source-capture`（栏目名与出口按钮文案）、`native-source-library`（栏目名与入口页表述）。
- 不引入别名兼容、术语映射或迁移层：统一到一个名字。

## Capabilities

### New Capabilities

无。本 change 只统一既有能力的命名，不新增能力。

### Modified Capabilities

- `native-mobile-foundation`：四栏命名「对话、收集、待处理、知识」改为「对话、收集箱、待处理、知识」，栏目引用同步为收集箱。
- `native-source-capture`：栏目名与提交出口按钮文案改为收集箱口径（「回到收集」→「回到收集箱」），交互与状态要求不变。
- `native-source-library`：入口页与列表场景中的栏目名引用同步为收集箱，列表行为不变。

## Impact

- `mobile/app/(tabs)/_layout.tsx`：底栏标签。
- `mobile/src/capture/components/`：`CaptureScreen.tsx`（页面标题与提示）、`SubmitOverlay.tsx`（出口按钮）、`PermissionPage.tsx`（返回按钮辅助名）、`CaptureHeader.tsx`（返回辅助名）及这些文件的测试断言。
- `mobile/src/sources/components/SourceDetailOverlay.tsx` 的返回辅助名与 `SourceLibrary.test.tsx` 断言同步。
- 不改接口、数据合同、权限与 AI 行为；不改 Web 与后端（它们已是「收集箱 / Source」口径）；不改采集与列表逻辑。
- `docs/prototypes/` 是历史产物，保持原样；命名以本 change 后的主规格为准。

## Non-Goals

- 「最近收集」区块名不改：它描述列表的新鲜度，不是栏目名。
- 不改 Web 与后端命名，不做跨端术语映射或双名兼容。
- 不改采集页、权限页、提交覆盖层与来源列表的行为、状态与文案结构（仅栏目名与出口按钮名）。
