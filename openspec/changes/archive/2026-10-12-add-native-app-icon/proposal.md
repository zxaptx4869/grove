## Why

原生 App 现在没有配置应用图标：`mobile/app.json` 里完全没有 `icon` 字段，`android.adaptiveIcon` 只有 `backgroundColor: "#F7F8F7"`（与页面底色相同的浅灰白），没有前景图。装出来的包因此显示平台/Expo 默认图标（用户看到的是默认机器人头像），而产品内的品牌标识早已确立为绿底白 G——对话页顶栏 `brandMark` 就是 `theme.green`（`#236748`）圆角方块 + 白色 G。启动器图标与产品内品牌标识不一致，是安装后第一眼可见的缺口。

## What Changes

- 新增 `mobile/assets/icon.png`（1024×1024，品牌绿底 + 白色 G 全出血，不含透明通道）作为 iOS/通用应用图标。
- 新增 `mobile/assets/adaptive-icon.png`（1024×1024，透明底白色 G）作为 Android 自适应图标前景。
- `mobile/app.json` 声明图标：`expo.icon`、`android.adaptiveIcon.foregroundImage`、`android.adaptiveIcon.monochromeImage`；`android.adaptiveIcon.backgroundColor` 由 `#F7F8F7` 改为品牌绿 `#236748`。
- 规格同步：`native-mobile-foundation` 新增「原生应用图标与品牌标识」要求。
- 不动运行时代码、不加依赖、不改品牌色与应用内图标（底栏/Agent 线稿保持原样）。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `native-mobile-foundation`：新增一条应用图标要求（图标与对话页 G 品牌标识同源、资产位置与 Android 自适应安全区），既有壳与导航要求不变。

## Impact

- `mobile/assets/`：新增目录与两张 PNG。
- `mobile/app.json`：`expo.icon`、`android.adaptiveIcon.*`。
- 不改接口、数据、权限、AI 行为与任何运行时代码；不改 Web 与后端。
- 生效范围受平台限制：Expo Go 看不到自定义图标，需要 development build 或 EAS 包；Android 启动器有图标缓存，可能需卸载重装。

## Non-Goals

- 不重做品牌视觉，不改 `theme.green`，不改应用内图标（底栏、Agent 线稿）。
- 不做启动画面（splash）与 Web favicon。
- 不引入渲染管线或构建期脚本；图标作为成品 PNG 入库。
- 不改原生工程结构与现有依赖。
