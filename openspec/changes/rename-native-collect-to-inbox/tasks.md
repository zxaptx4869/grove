## 1. 命名统一（原生代码）

- [x] 1.1 `mobile/app/(tabs)/_layout.tsx` 第二栏标签由「收集」改为「收集箱」
- [x] 1.2 `mobile/src/capture/components/CaptureScreen.tsx` 入口页标题改为「收集箱」，`READY_HINT` 与文件内注释中的栏目名同步
- [x] 1.3 `mobile/src/capture/components/SubmitOverlay.tsx` 出口按钮文案由「回到收集」改为「回到收集箱」（该 label 同时是辅助名）
- [x] 1.4 `CaptureHeader.tsx`、`SourceDetailOverlay.tsx` 的返回辅助名改为「返回收集箱列表」，`PermissionPage.tsx` 的返回按钮改为「返回收集箱」

## 2. 测试断言同步

- [x] 2.1 `mobile/src/capture/components/CaptureScreen.test.tsx` 中断言「回到收集」的 5 处用例与 3 处用例名改为新文案，用例原意不变（出口存在性、点击后回入口页并重新取数）
- [x] 2.2 `mobile/src/sources/components/SourceLibrary.test.tsx` 的「返回收集列表」断言与文件注释同步
- [x] 2.3 检索底栏标签相关断言：无按标签文本查询的用例，无需改动

## 3. 验证与走查

- [x] 3.1 `cd mobile && npm run typecheck && npm run lint && npm test` 全绿（typecheck 无输出、eslint 无告警、28 个套件 187 个用例通过）
- [x] 3.2 `openspec validate --all --strict` 通过（68 passed / 0 failed）
- [x] 3.4 `rg -n "回到收集|返回收集" mobile/src mobile/app` 无残留（栏目名相关文案已全部改为收集箱口径；「要收集的文字」「最近收集」等动作词与区块名按 Non-Goals 保留）
- [ ] 3.3 用户真机走查清单（未执行，待用户反馈）：底栏第二栏显示「收集箱」且不截断、不换行（含窄视口）；入口页标题为「收集箱」；提交结果页出口按钮为「回到收集箱」、点击后回到入口页并刷新列表；读屏播报与可见文案一致；采集 → 提交 → 返回的流转不回归
