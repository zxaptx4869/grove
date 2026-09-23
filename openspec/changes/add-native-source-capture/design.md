# 设计：原生采集入口与上传链路

## 1. 依赖与图片处理 API 形态

- 依赖用 `npx expo install expo-image-picker expo-image-manipulator` 安装，得到与 SDK 57 匹配的 `~57.0.19`，不手写版本号。
- 图片处理选用 `expo-image-manipulator` 的**新版 context API**：`ImageManipulator.manipulate(uri).resize(...).renderAsync()` 得到 `ImageRef`，再 `saveAsync({ compress: 0.8, format: SaveFormat.JPEG })` 得到结果文件。旧版 `manipulateAsync` 在本版本已标记 `@deprecated` 并被官方指向新 API，新代码不引入废弃入口；`useImageManipulator` 是 Hook 形态，采集是一次性异步动作，不需要组件内复用，故不用。
- `resize` 只传 `width` 会按比例换算高度，因此必须按朝向决定传哪一边：`width >= height` 时传 `width: 2048`，否则传 `height: 2048`，保证「长边 2048」而不是把竖图放大到 8192。
- 长边不超过 2048 时不调用 `resize`，只做 jpg 转码（HEIC 也必须转码，否则会被后端 400 拒绝）。
- 上传文件名用 `grove-<时间戳>-<序号>.jpg`、MIME 固定 `image/jpeg`：原始文件名（相册/相机的 IMG_xxxx、HEIC 后缀）不适合作为来源标题，也不适合作为 multipart 文件名。

## 2. 上传通道与超时

- 新增 `mobile/src/capture/upload.ts`，不复用 `mobile/src/api.ts` 的 `request()`（写死 `Content-Type: application/json` 且 12 秒超时，无法传 FormData）。
- 请求形态：`POST ${EXPO_PUBLIC_API_BASE_URL}/api/sources`，`FormData` 追加 `files`（React Native 的 `{ uri, name, type }` 对象）、`capture_key`，有值时再追加 `text` / `title` / `project_id` / `note`；`Authorization: Bearer <token>` 照常。**不设置 `Content-Type`**，交给平台生成 multipart boundary。
- 超时取 **90 秒**（`UPLOAD_TIMEOUT_MS = 90_000`）：客户端压缩后单张通常 0.3–1.5MB，1Mbps 上行约需 2–12 秒；即使压缩失效退到后端 10MB 上限，1Mbps 上行约需 80 秒，90 秒覆盖该最坏情况，同时远小于「用户以为卡死」的感知窗口。通用 JSON 请求的 12 秒对上传明显不足，故不复用。
- 超时用 `AbortController` 实现；失败**不自动重试**：幂等键虽然让自动重试安全，但自动重发会让用户看不到失败、也无法控制流量，弱网下反复挂起反而更糟。失败后由用户点「重试」，沿用该条的 `capture_key`。
- `200` 与 `201` 都表示成功（`201` 新建、`200` 命中已存在来源），响应体都是同一个 Source；解析时按 `response.ok` 判定，不区分状态码。
- 业务错误解析 `detail` 字段并原样透传；网络中断或超时无 `detail` 时用固定文案说明材料未保存。

## 3. 批次键与提交形态

- 采集动作开始时生成一个批次 UUID（`expo-crypto` 的 `randomUUID()`，RN 无 Web `crypto`）。第 i 个提交单元用 `capture_key = \`${batchId}:${i}\``，序号从 1 开始；UUID 36 字符 + 序号，远低于 128 上限。
- 「每张一条」= N 个提交单元，逐个单文件请求；「多张合并一条」= 1 个提交单元，一次请求带 N 个文件；文本 = 1 个提交单元带 `text`。
- 键随提交单元保存在状态里，重试读同一条目的键；批次一旦结束（用户开始新一轮采集）就重新生成 UUID，因此成功后再采一次会产生新来源。
- 标题：图片提交单元传 `title`，取 `图片 YYYY-MM-DD HH:mm`；「每张一条」且 N > 1 时追加 `· M/N` 便于在列表区分；「多张合并一条」追加 `· N 张`。文本不传 `title`，沿用后端「正文首行」的默认标题。

## 4. 状态机与模块划分

`mobile/src/capture/`：

- `image.ts`：`prepareImage(asset)`（朝向判断 + 压缩 + jpg 转码，返回 `{ uri, name, type, width, height }`）。
- `picker.ts`：权限检查/申请（`requestCameraPermissionsAsync` / `requestMediaLibraryPermissionsAsync`）、`launchCameraAsync`、`launchImageLibraryAsync({ allowsMultipleSelection: true, selectionLimit: 5 })`、`openAppSettings()`（`Linking.openSettings()`）。
- `batch.ts`：纯函数 `buildCaptureKey`、`createBatchItems`（按提交形态与张数派生条目）、`summarizeCapture`、`summaryText`、`progressText`；不含 React 与网络，便于单测。
- `submit.ts`：`submitCaptureItems(items, deps)` 串行执行器，`deps` 注入 `uploadFile` / `triggerProcessing` / `onItemUpdate`，返回更新后的条目；失败只标记该条，不中断循环。
- `upload.ts`：真实网络实现与 `CaptureSubmitError`（带 `status`）。
- `components/`：`CaptureScreen`（栏目主体）、`CaptureForm`、`EntryRow`、`AlbumChoiceSheet`、`ProjectSheet`、`PermissionNotice`、`SubmitStatus`。

条目状态：`pending → uploading → saved | failed`，另记 `processError` 表示「已保存但处理未启动」。汇总口径：`saved` 计入已提交，`failed` 计入未成功；全部成功 / 部分失败 / 全部失败由这两个计数派生，结果区在采集栏目内自包含展示，不依赖列表。

## 5. 权限与「去设置」

- 入口被点击时先 `get*PermissionsAsync`，未授权再 `request*PermissionsAsync`；返回非 `granted` 就渲染 `PermissionNotice`（用途说明 + 「系统不会再重复弹出授权」+「去设置」按钮，跳 `Linking.openSettings()`）。
- 权限被拒后不再次自动申请，避免反复弹窗；用户从设置返回后重新点击入口会重新检查权限状态。

## 6. 测试策略

- 纯逻辑（`batch.ts`）直接单测：键派生（重试复用、新一轮换键）、部分失败汇总与文案、进度文案。
- `submit.ts` 用注入的假上传器单测：串行顺序、部分失败继续、只重试失败项。
- `upload.ts` 用 `global.fetch` mock 单测：multipart 字段（含 `capture_key`、不设置 `Content-Type`）、超时中止、`detail` 原文透传、200/201 都算成功。
- `picker.ts` / `image.ts` / 组件测试用 `jest.mock` 替换 `expo-image-picker`、`expo-image-manipulator`、`expo-linking`，不依赖真机或模拟器；权限被拒场景断言提示文案与「去设置」动作。
- 模拟器与真机走查由用户执行，AI 不安装、不启动、不操作设备。

## 7. 与后端合同的其它约定

- 每条来源创建成功后立即 `POST /api/sources/{id}/process`。该端点对处理中或已完成来源返回 409 且不改状态，对等待处理来源保持等待处理，因此重复触发不会破坏状态或产生重复执行；移动端只需把失败呈现为「来源已保存，但处理启动失败」，不额外判断状态。
- 后端 400 文案（最多 5 张 / 单张 10MB / 仅 png/jpg/webp）原样展示，客户端不预判、不改写；张数上限由系统选择器与表单共同约束。
