## Context

已核对的事实（本 change 直接采用）：

- `mobile/app.json` 无 `icon` 字段；`android.adaptiveIcon` 只有 `backgroundColor: "#F7F8F7"`，与 `theme.bg` 同为页面底色，不是品牌绿。
- 对话页顶栏品牌标识已是绿底白 G：`mobile/src/knowledge-agent/components/ConversationScreen.tsx` 的 `brandMark`（34×34、圆角 8、`backgroundColor: theme.green`）+ 白色 `G` 文本；`theme.green = "#236748"`（`mobile/src/theme.ts`）。
- 仓库没有 `mobile/ios`、`mobile/android` 原生目录，属 Expo CNG/managed 工程，图标只能通过 `app.json` + `assets/` 配置。
- `docs/prototypes/README.md` 的「移动端原创图标方向」比较的是应用内图标（底栏与 Agent 的线稿方向），不涉及启动器图标；启动器图标对齐既有 G 品牌标识，与该记录不冲突。

## Goals / Non-Goals

**Goals:**

- 安装后主屏/启动器图标为绿底白 G，不再是 Expo 或平台默认图标。
- iOS 图标无透明通道、无黑边；Android 在圆形与圆角方形遮罩下 G 完整不被裁切。
- 只改配置与资产，不改运行时代码与依赖。

**Non-Goals:**

- 不重做品牌视觉、不改 `theme.green`、不改应用内图标。
- 不做 splash、Web favicon、图标生成脚本或构建期管线。

## Decisions

**决策 1：图标沿用对话页品牌标识的形状（品牌绿圆角方块 + 白色 G），不新造图形。**
应用内已经有 G 品牌标识（顶栏 `brandMark`、Agent 头像 `agentDotText`），启动器图标与它同源可让"安装后的第一屏"与产品内一致；自造一个新图形会立刻产生第二套品牌视觉。

**决策 2：iOS/通用与 Android 前景分成两份资产，iOS 那份不含透明通道。**
iOS 图标含 alpha 会被 App Store 判为无效图片；Android 自适应图标必须是透明底前景 + 背景色。两份资产分开可以同时满足两端，且不需要平台分支构建。

**决策 3：`android.adaptiveIcon.backgroundColor` 由 `#F7F8F7` 改为 `#236748`。**
现有值是页面底色；不改它会让自适应图标的背景变成浅灰白，与绿色前景脱节。

**决策 4：`monochromeImage` 复用同一前景文件。**
Android 13+ 主题图标需要单色轮廓，现有前景即白色 G + 透明底，其 alpha 轮廓已满足要求，不需要额外资产。此项为可选增强：若真机主题图标表现不佳，可单独移除该字段而不影响主图标。

**决策 5：资产以一次性脚本渲染（HTML + 无头 Chrome），脚本不入库，只入库 PNG 成品。**
图标是品牌成品而非需要在仓库里维护的渲染管线。为便于复现，记录生成参数：字体 `Helvetica Neue / Helvetica / Arial` Bold，字距 `-0.02em`；iOS 图 1024×1024、底色 `#236748`、字号 656px、整体下移 26px；Android 前景 1024×1024、透明底、字号 438px、整体下移 16px（G 落在 108dp 图层的 72dp 安全区内）。

## Risks / Migration

- Expo Go 不生效：必须在 development build 或 EAS 包上验证。
- Android 启动器有图标缓存，改图标后可能需要卸载重装才刷新；系统最近任务里的旧图标属缓存，不是配置错误。
- `monochromeImage` 的主题图标效果依赖 Android 13+ 与启动器实现，属真机走查项。
- 回滚：删除两张资产与 `app.json` 中新增字段即可，无数据与接口影响。
