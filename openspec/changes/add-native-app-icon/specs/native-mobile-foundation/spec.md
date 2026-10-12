## ADDED Requirements

### Requirement: 原生应用图标与品牌标识
原生 App MUST 配置与对话页 G 品牌标识同源的应用图标：品牌绿 `#236748` 底、白色 G。iOS/通用图标 MUST 为 1024×1024 全出血且不含透明通道；Android MUST 使用自适应图标，前景为透明底白色 G 且完整落在 108dp 图层的 72dp 安全区内，背景为品牌绿。图标资源 MUST 位于 `mobile/assets/` 并在 `mobile/app.json` 声明，MUST NOT 依赖 Expo 或平台默认图标。

#### Scenario: 安装后显示品牌图标
- **WHEN** 用户在 development build 或正式包上查看主屏与任务切换器
- **THEN** 应用图标为绿底白色 G，不再是 Expo 或平台默认图标

#### Scenario: Android 自适应图标遮罩安全区
- **WHEN** Android 以圆形、圆角方形或方形遮罩渲染图标
- **THEN** G 完整可见且不被遮罩裁切，图标背景为品牌绿

#### Scenario: 主题图标可辨识
- **WHEN** Android 13+ 用户启用主题图标（单色图标）
- **THEN** 图标以单色 G 轮廓呈现，仍可辨识为同一品牌标识
