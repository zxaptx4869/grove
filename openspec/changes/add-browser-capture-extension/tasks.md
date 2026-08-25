## 1. OpenSpec 工件

- [x] 1.1 创建 change `add-browser-capture-extension` 并编写 proposal / specs / design / tasks
- [x] 1.2 `openspec validate --all --strict` 通过

## 2. 扩展工程骨架

- [x] 2.1 `browser-extension/`：Manifest V3 + TypeScript + Vite（`@crxjs/vite-plugin`）工程，含图标、popup、content script、background 入口
- [x] 2.2 注册快捷键 `Cmd+S`（冲突则退 `Cmd+Shift+S`）与扩展图标点击行为

## 3. 框选截图

- [x] 3.1 清晰度 spike：`captureVisibleTab` 位图裁剪定稿（DOM 裁剪对复杂页面易失真，不实现）
- [x] 3.2 content script 遮罩：进入框选模式、拖框、尺寸提示、松手生成截图预览、取消

## 4. 批次与发送

- [x] 4.1 批次存储：IndexedDB 存图片 Blob，批次元数据持久化；预览条显示张数、取消单张
- [x] 4.2 background 发送：`GET /api/me` 登录校验；multipart 多图一次提交为同一 Source；成功/失败反馈与「查看收集箱」入口

## 5. 引导与设置

- [x] 5.1 popup：快捷键说明、批次状态、首次引导文案
- [x] 5.2 设置：Grove 服务器地址配置（默认本地 dev）并持久化

## 6. 验证与收尾

- [x] 6.1 本地开发者模式加载扩展；在真实页面（小红书/知乎）端到端走查：框选 → 预览/暂存/发送 → 收集箱 Source → 确认流程（用户已本地走查通过）
- [ ] 6.2 `openspec validate --all --strict` 通过后归档同步主规格
- [ ] 6.3 本地提交（不 push、不 merge）
