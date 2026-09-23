## 1. 规划工件与依赖

- [ ] 1.1 四类工件齐备并通过 `openspec validate --all --strict`。
- [ ] 1.2 `npx expo install expo-image-picker expo-image-manipulator` 安装 SDK 57 匹配版本，`mobile/package.json` 记录依赖。

## 2. 采集逻辑模块

- [ ] 2.1 `src/capture/batch.ts`：批次键派生（`{batchId}:{i}`，序号从 1）、提交单元派生（每张一条 / 合并一条 / 文本）、标题派生、汇总与进度文案。验收：单测覆盖重试复用键、新一轮换键、标题形态。
- [ ] 2.2 `src/capture/submit.ts`：串行执行器，逐条上传并在成功后触发处理，部分失败继续、只重试失败项。验收：注入假上传器断言顺序、部分失败汇总文案、失败项重试。
- [ ] 2.3 `src/capture/upload.ts`：multipart 上传通道（`files`/`capture_key`/可选字段、不设置 `Content-Type`、90 秒超时、`detail` 透传、200 与 201 都成功、不自动重试）。验收：fetch mock 断言字段、超时中止与错误文案。
- [ ] 2.4 `src/capture/image.ts` 与 `src/capture/picker.ts`：按朝向压缩到长边 2048 并转 jpg、不放大、HEIC 转码；权限检查/申请、「去设置」跳转、相机单张与相册多选（`selectionLimit: 5`）。

## 3. 采集界面

- [ ] 3.1 收集栏目替换占位：三入口横排（相机 / 相册 / 文本），相册下钻「每张一条 / 多张合并一条」。
- [ ] 3.2 采集表单：补充说明 + 所属项目（默认未归属），图片不提供正文输入；缩略图可逐张移除、相机来源可重拍。
- [ ] 3.3 结果反馈：进行中（含「正在上传 N 张中的第 M 张」）、全部成功、部分失败（「已提交 M 条，N−M 条未成功」+ 逐项重试）、全部失败、上传失败与处理启动失败分别提示、400 原文透传。
- [ ] 3.4 权限被拒：用途说明 + 「去设置」入口，不反复弹窗。验收：组件测试断言文案与跳转动作。

## 4. 验证与收尾

- [ ] 4.1 `cd mobile && npm run lint && npm run typecheck && npm test` 全部通过。
- [ ] 4.2 用 `curl` 冒烟核对后端合同：multipart 提交 + `capture_key` 同键重复提交返回 200，确认移动端假设与实现一致。
- [ ] 4.3 每段可验证修改做本地提交（中文 Conventional Commits），输出改动清单、规格条目、验证命令与结果、未验证项与真机走查清单；**不推送、不合并、不归档**，停下等人工验收。
