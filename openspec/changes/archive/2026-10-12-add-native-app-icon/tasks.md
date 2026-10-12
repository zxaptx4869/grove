## 1. 资产与配置

- [x] 1.1 落库 `mobile/assets/icon.png`（1024×1024、无 alpha、品牌绿底白色 G、全出血）
- [x] 1.2 落库 `mobile/assets/adaptive-icon.png`（1024×1024、透明底白色 G、G 在 72dp 安全区内）
- [x] 1.3 `mobile/app.json` 声明 `expo.icon`、`android.adaptiveIcon.foregroundImage`、`android.adaptiveIcon.monochromeImage`，并把 `adaptiveIcon.backgroundColor` 改为 `#236748`
- [x] 1.4 规格同步：`native-mobile-foundation` 新增「原生应用图标与品牌标识」要求

## 2. 验证与走查

- [x] 2.1 `mobile/app.json` JSON 合法，且 `npx expo config --type public` 能解析出图标字段
- [x] 2.2 `cd mobile && npm run typecheck && npm run lint && npm test` 无回归
- [x] 2.3 `openspec validate --all --strict` 通过
- [x] 2.4 用户确认可归档（2026-10-12）：图标渲染稿与 Expo Go 中的呈现已确认；主屏启动器图标（含 Android 圆形/圆角遮罩、主题图标与旧图标缓存）留待用户后续打 development build / EAS 包时复核
