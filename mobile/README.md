# Grove 原生移动端

本目录是独立的 Expo managed/CNG React Native 工程，不是 Grove Web 的移动适配，也不使用 WebView。它与 Grove 后端共用账号、Workspace、项目、Session 和后续知识 Agent API。

## 启动

```bash
cp .env.example .env
npm install
npm start
```

Android 真机通过 Expo Go 连接开发服务器时，电脑和手机必须能互相访问局域网地址。局域网、访客 Wi-Fi 或防火墙导致无法下载开发更新时，改用 `npm run start -- --tunnel`，再重新扫描终端给出的二维码。不要把 Expo Web 预览当作原生端替代验收。

在电脑浏览器快速预览应用壳可执行 `npm run web`。这是 Expo Web 预览，不代表 iOS/Android 原生端已完成验证。
后端本机配置的 `FRONTEND_ORIGINS` 还必须包含 `http://localhost:8081` 与 `http://127.0.0.1:8081`，否则浏览器会阻止登录请求。

`EXPO_PUBLIC_API_BASE_URL` 必须是运行设备可访问的 Grove 后端地址，且不应写死在代码中：iOS Simulator 使用 `http://127.0.0.1:8000`；Android Emulator 使用 `http://10.0.2.2:8000`；局域网真机使用开发电脑的局域网 IP；部署后改为 HTTPS API 地址。后端开发服务需绑定到真机可访问的网络接口时，请按本机网络与防火墙设置启动。

`npm run ios` 固定以 IPv4 localhost 启动 Metro，避免较新 Node.js 将 `localhost` 优先解析为 `::1`，但 Expo Go 仍打开 `exp://127.0.0.1:8081`，从而显示 `Could not connect to the server`。需要清理 Metro 缓存时执行 `npm run ios -- --clear`。

## 校验

```bash
npm run lint
npm run typecheck
npm test -- --runInBand
```

`npm run ios` 和 `npm run android` 分别需要安装对应平台的 Xcode/Simulator 与 Android SDK/模拟器；本工程不提交手工维护的 `ios/` 或 `android/` 目录。
