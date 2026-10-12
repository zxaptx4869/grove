## 1. 资产与配置

- [x] 1.1 落库 `mobile/assets/icon.png`（1024×1024、无 alpha、品牌绿底白色 G、全出血）
- [x] 1.2 落库 `mobile/assets/adaptive-icon.png`（1024×1024、透明底白色 G、G 在 72dp 安全区内）
- [x] 1.3 `mobile/app.json` 声明 `expo.icon`、`android.adaptiveIcon.foregroundImage`、`android.adaptiveIcon.monochromeImage`，并把 `adaptiveIcon.backgroundColor` 改为 `#236748`
- [x] 1.4 规格同步：`native-mobile-foundation` 新增「原生应用图标与品牌标识」要求

## 2. 验证与走查

- [x] 2.1 `mobile/app.json` JSON 合法，且 `npx expo config --type public` 能解析出图标字段
- [x] 2.2 `cd mobile && npm run typecheck && npm run lint && npm test` 无回归
- [x] 2.3 `openspec validate --all --strict` 通过
- [ ] 2.4 用户真机走查（未执行，待用户反馈）：development build 或 EAS 包安装后主屏图标为绿底白 G；Android 圆形/圆角方形遮罩下 G 不被裁切；iOS 图标不透明、无黑边；Android 13+ 主题图标可辨识；旧图标缓存已刷新
