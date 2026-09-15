## Why

实验工作台的统一 `dialogue_loop` 已经在 Grove 真实 Workspace、Entry、Source 和权限边界上验证了连续对话、工具循环、候选稿和部分完成行为。正式 Knowledge Agent 仍使用另一套多级规划执行图，造成同一模型在 Web 中表现、速度和状态语义与实验台不一致，继续修补两套编排会持续扩大复杂度。

本变更以实验台统一循环作为正式 Web Agent 的唯一编排核心，保留 Grove 正式会话、持久化、鉴权和数据边界，并为后续移动端复用同一后端入口打基础。

## What Changes

- 增加正式 API 到统一 `dialogue_loop` 的生产适配层。
- 将正式 Conversation、Message、Run、Workspace 和用户权限映射为循环所需的运行状态，并在轮次结束后保存回答、工具记录、模型调用、状态和 continuation。
- 正式 Web Agent 使用实验台已经验证的工具循环、结果句柄、finalizer、候选稿和部分完成语义。
- 明确禁止同一 Web 请求同时经过旧多级规划执行图和统一循环。
- 定义稳定的结构化回答块与轮次状态响应，供 Web 先接入、移动端后复用。
- 增加适配层的确定性测试和短链路 API 验证入口；真实模型人工验收独立进行。

### Non-Goals

- 本变更不直接实现 Web 页面或移动端页面。
- 不搬运实验台 JSON 存储、进程内工作台状态、实验启动服务或调试展示字段。
- 不改变 Entry、Source、Workspace、权限和正式写入合同。
- 不新增意图分类、规划、摘要或完成度评分模型。
- 不提高模型、工具、上下文或时间预算。
- 不在同一变更中清理所有旧 Agent 业务文件；仅切换 Web Agent 的执行入口并保留可回滚边界。

## Capabilities

### New Capabilities

- `knowledge-agent-dialogue-loop-production-adapter`: 将统一对话循环适配到正式会话 API、持久化和多用户运行环境。

### Modified Capabilities

- 无。现有正式数据、权限和写入规格保持不变；本变更新增 Web Agent 的执行适配能力。

## Impact

- 后端：`backend/evals/dialogue_loop/` 的可复用核心、正式 `knowledge_agent` 服务、Conversation/Run/Message 持久化和 API 入口。
- 测试：统一循环与正式服务之间的状态映射、重复请求、取消、失败恢复、Workspace 隔离和结果块合同。
- 前端：本变更只定义可消费的响应合同，不接入 Web 页面；后续 Web change 复用该合同并移除运行状态面板。
- 无数据库迁移目标；如实施中发现持久化缺少不可替代字段，必须单独说明并缩小迁移范围。
