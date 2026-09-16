## 1. 确定性回归基线

- [ ] 1.1 用 Run 13 的 8295/9290 投影、5 条候选和成功工具事件建立共享循环失败回归，覆盖不依赖候选与依赖候选两类任务
- [ ] 1.2 从 `session-20260916-130250` 固化真实 1002 字符损坏 `INVALID_JSON`，并补充内层合法包装、未知结构和非法引用对照
- [ ] 1.3 为硬上限、真实 Provider 失败、未筛选与真实空结果、无工具收尾、续接不重复查询、权限变化和失效句柄补齐确定性断言

## 2. 共享收尾与恢复

- [ ] 2.1 在输出校验重试前只保留通过内容边界的文本与通用知识标注，隔离未授权结构块
- [ ] 2.2 让软阈值统一进入无工具 finalizer，并按真实结果区分完成、部分完成和未执行
- [ ] 2.3 实现 `relevance_selection` 最小 continuation、恢复前 Workspace/权限/范围/对象/指纹复验及成功查询复用
- [ ] 2.4 实现严格 `INVALID_JSON` 解包兼容，损坏内层保持 finalize-only 恢复且不增加重试
- [ ] 2.5 将 `finalize_transition` 记录为 `not_dispatched`，并回归真实模型失败仍为 `model_call_failed`

## 3. 正式阶段传播与 Web

- [ ] 3.1 将去重后的 activity callback 阶段写入现有 Run 快照并通过 `dialogue_stage` 返回，保持 `current_step=dialogue_loop`
- [ ] 3.2 在终态、异常和取消路径关闭阶段发布并清空活动阶段，验证刷新和 continuation 不残留旧状态
- [ ] 3.3 正式 Web 按真实阶段显示轻量提示，补齐终态停止、会话切换、未知阶段回退、`aria-live` 与减少动画偏好测试

## 4. 跨入口验证与收尾

- [ ] 4.1 用相同状态、历史、模型响应夹具验证实验台共享循环与 production adapter 的块、终态、continuation 和审计一致
- [ ] 4.2 运行相关后端测试、ruff、Web 测试/lint/build 和 `openspec validate --all --strict`，记录基线失败与实际结果
- [ ] 4.3 核对冻结预算常量与无付费模型调用，更新任务状态并形成重启说明和人工语义/视觉走查清单
