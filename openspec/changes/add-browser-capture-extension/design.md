## Context

explore 结论：手机端采集随原生 App 单独规划（本轮不做）；电脑端集中整理需要「框选截图 → 批次发送 → 一键进收集箱」。用户真实来源主要是浏览器内网页（小红书/知乎等），框选截图可覆盖；长文分段截图用批次保持上下文。范围定为 Chrome（Chromium 系）扩展，本地开发者模式加载，不上商店。

## Goals / Non-Goals

**Goals:**

- 浏览器页面内框选截图（整页=框满视口，局部=拖框）；
- 批次管理：追加、取消、显式发送，一个 Source 多图进收集箱；
- 复用浏览器登录会话，未登录引导登录；
- 首次引导与服务器地址配置。

**Non-Goals:**

- 不做商店上架、Firefox / Safari、无痕模式适配；
- 不做长截图、桌面截图工具、移动端采集；
- 发送时不选项目、不填备注（归属交 AI 推荐）；
- 不支持浏览器内置页与 Chrome 内置 PDF 查看器。

## Decisions

### D1：技术栈与工程结构

Manifest V3 + TypeScript，构建用 Vite + `@crxjs/vite-plugin`（支持热更新与多入口）；代码放仓库子目录 `browser-extension/`，与主仓库同一 OpenSpec 流程管理。

### D2：框选截图实现

content script 注入遮罩层（fixed 全屏 + 拖框 + 尺寸提示）；裁剪使用 `chrome.tabs.captureVisibleTab` 位图 + 按选区坐标裁剪（乘 `devicePixelRatio`）。spike 结论（2026-08-25）：DOM 裁剪（canvas 重绘）对小红书等复杂页面（懒加载图片、跨域资源、CSS 滤镜）易失真或失败，`captureVisibleTab` 是浏览器原生渲染位图、与用户所见一致，清晰度最适合作 OCR 输入；DOM 裁剪不实现。无头 Chrome 冒烟已验证扩展可加载；真实页面清晰度在端到端走查中确认。

### D3：批次存储

截图图片以 Blob 存入 IndexedDB（规避 `chrome.storage.local` 配额），批次元数据（张数、缩略图、状态）由 popup/background 维护并在会话间持久化。

### D4：发送链路

background 用 `fetch` 以 multipart 直传 Grove `POST /api/sources`（host_permissions 覆盖配置的服务器地址，不受 CORS 限制）；多图一次提交为同一 Source 的多个附件；发送前先 `GET /api/me` 校验登录态，401 时提示并打开登录页。发送成功后轻提示「已发送到收集箱」，可点击跳转收集箱。

### D5：快捷键

按用户确认使用 `Cmd+S`（macOS）注册 `chrome.commands`；实测（2026-08-25）被浏览器「保存网页」占用，已退为 `Cmd+Shift+S`（macOS）/ `Ctrl+Shift+S`（Windows），并在弹窗引导与 README 中同步说明。

### D6：popup 与引导

popup 展示快捷键、当前批次张数、使用说明与「打开设置」；设置项仅包含 Grove 服务器地址（默认本地 dev）。首次安装显示简短引导文案。

### D7：后端适配

预期后端零改动：`create_source` 已支持多图 multipart，图片附件走现有 OCR 与整理链路。联调时验证 session cookie 域与扩展请求一致。

## Risks / Trade-offs

- [Cmd+S 与浏览器保存冲突] → 实施时验证注册，冲突则退 Cmd+Shift+S（记入引导）。
- [框选清晰度影响 OCR] → 先做 spike 对比 captureVisibleTab 与 DOM 裁剪，选更清晰方案。
- [图片存储配额] → 用 IndexedDB 规避 storage 配额限制。
- [内置页不可注入] → 作为 Non-Goal，给明确提示即可。

## Migration Plan

纯新增扩展工程，无数据库与后端变更。

## Open Questions

- 无（spike 已定稿：captureVisibleTab 位图裁剪；快捷键注册与页面清晰度在端到端走查中确认）。
