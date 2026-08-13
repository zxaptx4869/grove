## Why

项目、目录和来源采集已经具备基础能力，但后续 Organizing / Directory / Reader Agent 需要共享一份稳定的「项目上下文」，避免每个 Agent 各自对项目做出互相矛盾的总结。当前项目说明和正式目录是仅有的可生成上下文输入，因此先落地 Project Context Snapshot 的初始版本：基于项目说明与正式目录生成项目概要，并支持异步更新、防抖、失败回退、展示与纠正。

本 change 只做 P0-A 第 4 项的初始版本，不提前纳入已确认 Entry、知识覆盖和近期主题（这些依赖尚未实现的 Entry，留给 `enhance-project-context-with-entries`）。

## What Changes

- 新增 `project-context` 能力：
  - `ProjectContext` 模型：每个 Project 至多一份上下文快照，按 Workspace 隔离；
  - 初始概要生成：基于项目说明与正式目录节点生成项目概要、当前关注方向与目录主题；
  - 更新触发与防抖：项目说明或正式目录变化后异步更新，短时间多次变化合并为一次；
  - 失败回退：生成失败时保留上一份有效快照，无快照时标记失败并保留错误；
  - 展示与纠正：用户可查看、纠正项目概要与当前关注方向，纠正作为高优先级约束保留；
  - Agent 公共上下文接口：提供结构化项目上下文供后续 Agent 共享。

## Capabilities

### New Capabilities

- `project-context`: ProjectContext 模型、初始概要生成、异步防抖更新、失败回退、展示与纠正、Agent 公共上下文接口。

### Modified Capabilities

（无）

## Impact

- 后端：新增 `ProjectContext` 模型与 Alembic 迁移；新增 `ProjectContextGenerator` 抽象（Demo 确定性实现 + 未接入桩）；新增项目上下文 Worker（进程内异步、按 `refresh_due_at` 防抖领取）；新增项目上下文 API（查询、纠正、手动重新生成）；在项目创建、项目说明更新、目录节点变更处触发刷新。
- 前端：项目首页展示项目上下文快照，提供「纠正」与「重新生成」入口；扩展 `lib/api` 客户端与 `queryKeys`。
- 配置：新增上下文生成器、刷新防抖时长、上下文 Worker 开关配置；更新 `backend/.env.example`。
- 无外部服务依赖；本轮不接入真实 Agent / PydanticAI。

## Non-Goals

- 不纳入已确认 Entry、知识覆盖、近期主题与上下文版本（留给 `enhance-project-context-with-entries`）。
- 不实现 OCR、语义拆分或 Candidate 生成（留给 `add-organizing-agent-extraction`）。
- 不实现 Directory / Reader / Discovery Agent 或 PydanticAI 接入。
- 不引入独立任务队列（Celery/RQ/Redis）。
- 不使用待确认 Candidate 生成上下文。
- 不把 AI 生成的上下文直接写入正式 Entry 或正式目录；它始终是可查看、可纠正的派生上下文。
