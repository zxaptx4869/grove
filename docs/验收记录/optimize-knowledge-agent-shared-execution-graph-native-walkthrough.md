# Knowledge Agent 共享执行图原生端兼容走查

来源 change：`optimize-knowledge-agent-shared-execution-graph`（任务 6.4）

日期：2026-09-04

> 状态：自动化已通过，等待用户在真机完成兼容走查并反馈。本 change 不新增 UI，走查
> 目标是确认共享执行层没有改变既有回答、Citation、状态和历史恢复体验。

## 自动化结果

```text
Jest：12 suites / 145 tests 全部通过
TypeScript：通过
ESLint：通过
```

测试过程中出现一条既有 React 测试 `act(...)` 控制台警告，不影响测试结果；本 change
没有修改原生组件或交互代码。

## 真机走查清单

建议使用已有正式 Entry 和 Source 的 Workspace；若能切换共享执行图开关，可用同一问题
分别执行一次，重点比较结果语义，不以肉眼感知的耗时作为唯一结论。

1. 在 Workspace 或项目范围提问一个同时包含“解释 + 结合我的知识 + 统计”的复合问题。
   回答正文、要点、依据概览和统计应正常显示，不出现 graph、node、fingerprint、内部查询
   或结果句柄。
2. 打开一条 Citation，确认 Entry 标题、Source 原文片段和生成时范围仍可达；返回对话后
   滚动位置与内容保持正常。
3. 使用一个只能得到部分 Grove 依据的问题，确认 partial/知识不足/fallback 信息明确，
   已有可用内容不会消失，完成态不再显示“正在处理”。
4. 在 Run 执行中取消一次，确认停止后不会出现迟到的正常回答或新增 Citation；如任务已
   先完成，取消应保持终态且不破坏内容。
5. 完全退出并重新打开 App，再进入同一 Conversation；历史回答、Citation、依据概览、
   partial/fallback 状态应与生成时一致，不触发可见的重复回答。
6. 切换 Workspace/项目范围后再提问，确认回答范围可见，且不会出现另一范围的 Entry 或
   Citation。
7. 在真机键盘展开/收起、底部安全区、长回答滚动和 VoiceOver/TalkBack 基本导航下确认
   没有遮挡、横向溢出、无法关闭的弹层或无名称的关键按钮。

## 用户反馈

待填写：通过 / 未通过，以及设备、系统版本和失败场景。用户反馈通过后才能将任务 6.4
标记完成并归档 change。
