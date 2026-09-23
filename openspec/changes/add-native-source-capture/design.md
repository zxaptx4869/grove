# 设计：原生采集入口与上传链路

## 1. 依赖与图片处理 API 形态

- 依赖用 `npx expo install expo-image-picker expo-image-manipulator` 安装，得到与 SDK 57 匹配的 `~57.0.19`，不手写版本号。文本入口的「从剪贴板填入」另需 `expo-clipboard`（`~57.0.2`，同样用 `npx expo install`），因为 React Native 核心已不再提供剪贴板读取，而规划与原型都要求该入口；这是本 change 相对提示词依赖清单的唯一追加。
- 图片处理选用 `expo-image-manipulator` 的**新版 context API**：`ImageManipulator.manipulate(uri).resize(...).renderAsync()` 得到 `ImageRef`，再 `saveAsync({ compress: 0.8, format: SaveFormat.JPEG })` 得到结果文件。旧版 `manipulateAsync` 在本版本已标记 `@deprecated` 并被官方指向新 API，新代码不引入废弃入口；`useImageManipulator` 是 Hook 形态，采集是一次性异步动作，不需要组件内复用，故不用。
- `resize` 只传 `width` 会按比例换算高度，因此必须按朝向决定传哪一边：`width >= height` 时传 `width: 2048`，否则传 `height: 2048`，保证「长边 2048」而不是把竖图放大到 8192。
- 长边不超过 2048 时不调用 `resize`，只做 jpg 转码（HEIC 也必须转码，否则会被后端 400 拒绝）。
- 系统选择器偶尔给出 0 宽高（无法判断长边）：此时跳过 `resize`，只做 jpg 转码与 quality 0.8 压缩，宁可少缩一次也不按错误方向放大。
- `app.json` 为 `expo-image-picker` 注册插件并给出中文权限文案（`photosPermission` / `cameraPermission`），同时把 `microphonePermission` 设为 `false`：采集只拍照片、不录音，避免构建时写入用不到的麦克风权限与系统提示。
- 上传文件名用 `grove-<时间戳>-<序号>.jpg`、MIME 固定 `image/jpeg`：原始文件名（相册/相机的 IMG_xxxx、HEIC 后缀）不适合作为来源标题，也不适合作为 multipart 文件名。

## 2. 上传通道与超时

- 新增 `mobile/src/capture/upload.ts`，不复用 `mobile/src/api.ts` 的 `request()`（写死 `Content-Type: application/json` 且 12 秒超时，无法传 FormData）。
- 请求形态：`POST ${EXPO_PUBLIC_API_BASE_URL}/api/sources`，`FormData` 追加 `files`、`capture_key`，有值时再追加 `text` / `title` / `project_id` / `note`；`Authorization: Bearer <token>` 照常。**不设置 `Content-Type`**，boundary 由 fetch 自己生成（`expo/fetch` 的 `RequestUtils` 会写入 `multipart/form-data; boundary=...`）。
- **文件部件形态（相对提示词的有意偏离）**：SDK 57 起 Expo 用 `expo/fetch` 接管全局 `fetch`，它自己把 FormData 序列化成字节，只接受 string / `Blob` / 带 `bytes()` 的对象；提示词给的 RN 经典 `{ uri, name, type }` 部件会在发送前抛 `Error: Unsupported FormDataPart implementation`（真机 2026-09-23 验收复现，后端零日志）。因此文件改用 `expo-file-system` 的 `new File(uri)` 承载（原生类，实现 Blob 接口含 `bytes()`，文件名与 MIME 由它提供），字段名与后端合同不变。
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

采集栏目是「三个互斥页面 + 一个全屏覆盖层」的状态机，对齐原型的 `setPage()` 与 `#submitOverlay`：`page: "entry" | "form" | "permission"`，覆盖层由 `submitOpen` 单独控制。

- `entry`：标题、副句与三入口横排，不渲染表单与结果区。原型入口页的「最近收集」列表属后续来源列表 change，本 change 不实现。
- `form`：独立滚动页，顶栏左侧返回箭头（丢弃草稿回入口页）、居中类型标题（相机 / 相册 / 文本）；底部固定提交条位于底部导航之上，iOS 键盘弹出时按键盘高度上移（Android 走窗口 resize，配合 `tabBarHideOnKeyboard` 不遮挡）。
- `permission`：权限被拒时替换整页（不再是入口页上的浮层），顶栏可返回入口页。
- `submit` 覆盖层：全屏 `Modal`（`statusBarTranslucent`）盖住页面内容与底部导航，标题「提交材料」/ 失败时「提交未成功」，无底部按钮；关闭或「回到收集」清空草稿、提交会话与批次键后回入口页。进行中不提供关闭出口，返回键不关闭，避免重复进入采集页。

`mobile/src/capture/`：

- `image.ts`：`prepareImage(asset)`（朝向判断 + 压缩 + jpg 转码，返回 `{ uri, name, type, width, height }`）。
- `picker.ts`：权限检查/申请（`requestCameraPermissionsAsync` / `requestMediaLibraryPermissionsAsync`）、`launchCameraAsync`、`launchImageLibraryAsync({ allowsMultipleSelection: true, selectionLimit: 5 })`、`openAppSettings()`（`Linking.openSettings()`）。
- `batch.ts`：纯函数 `buildCaptureKey`、`createCaptureSubmitUnits`（按提交形态与张数派生提交单元）、`createCaptureResults`、`summarizeCapture`、`summaryText`、`progressText`；不含 React 与网络，便于单测。
- `submit.ts`：`submitCaptureUnits(units, deps)` 串行执行器，`deps` 注入 `upload` / `triggerProcessing` / `onUpdate`；失败只标记该条，不中断循环。
- `upload.ts`：真实网络实现与 `CaptureSubmitError`（带 `status`）；失败时 `console.warn` 打印 url / 文件 uri / 幂等键 / 真实原因，避免「网络连接中断」掩盖真实错误（开发模式下并在文案后附「诊断：…」）。
- `components/`：`CaptureScreen`（页面状态机主体）、`CaptureHeader`、`CaptureForm`、`EntryRow`、`AlbumChoiceSheet`、`ProjectSheet`、`PermissionPage`、`SubmitOverlay`。

条目状态：`pending → uploading → saved | failed`，另记 `processError` 表示「已保存但处理未启动」。汇总口径：`saved` 计入已提交，`failed` 计入未成功；全部成功 / 部分失败 / 全部失败由这两个计数派生，在提交覆盖层内自包含展示，不依赖列表。

## 5. 权限与「去设置」

- 入口被点击时先 `get*PermissionsAsync`，未授权再 `request*PermissionsAsync`；返回非 `granted` 就切到独立权限页 `PermissionPage`（用途说明 + 「系统不会再重复弹出授权」+「去设置」按钮，跳 `Linking.openSettings()`），页内返回回入口页。
- 权限被拒后不再次自动申请，避免反复弹窗；用户从设置返回后重新点击入口会重新检查权限状态。

## 6. 测试策略

- 纯逻辑（`batch.ts`）直接单测：键派生（重试复用、新一轮换键）、部分失败汇总与文案、进度文案。
- `submit.ts` 用注入的假上传器单测：串行顺序、部分失败继续、只重试失败项。
- `upload.ts` 用 `global.fetch` mock 单测：multipart 字段（含 `capture_key`、不设置 `Content-Type`）、超时中止、`detail` 原文透传、200/201 都算成功。FormData 用 `src/capture/testing/expo-fetch-formdata.ts` 替身，按 Expo 的契约只接受 string 与带 `bytes()` 的部件，因此「退回 `{ uri, name, type }`」会被测试直接拦下（jest 里 Node 自带的 undici FormData 与运行时契约不同，不能用真身）。
- `picker.ts` / `image.ts` / 组件测试用 `jest.mock` 替换 `expo-image-picker`、`expo-image-manipulator`、`expo-linking`，不依赖真机或模拟器；权限被拒场景断言提示文案与「去设置」动作。
- 模拟器与真机走查由用户执行，AI 不安装、不启动、不操作设备。

## 7. 与后端合同的其它约定

- 每条来源创建成功后立即 `POST /api/sources/{id}/process`。该端点对处理中或已完成来源返回 409 且不改状态，对等待处理来源保持等待处理，因此重复触发不会破坏状态或产生重复执行。移动端把 **409 视为正常**（来源已在处理或已完成，幂等重试命中旧来源时会出现），不提示处理启动失败；只有其它失败才呈现为「来源已保存，但处理启动失败」并允许重试处理。
- 后端 400 文案（最多 5 张 / 单张 10MB / 仅 png/jpg/webp）原样展示，客户端不预判、不改写；张数上限由系统选择器与表单共同约束。
