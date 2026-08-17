## 1. 变更工件与基线

- [x] 1.1 运行 `openspec validate --all --strict`，确认本 change 四个工件校验通过
- [x] 1.2 确认分支为 `codex/add-batch-candidate-review`，工作区无无关改动

## 2. 后端接口与服务

- [x] 2.1 新增项目级批量候选列表接口：返回待采纳候选、来源标题/说明与 `review_band`
- [x] 2.2 新增项目级批量决策接口：`confirm` 逐条创建 Entry，`reject` 改状态，返回逐条结果
- [x] 2.3 实现快审/精审分流规则与 Workspace 归属校验
- [x] 2.4 批量确认支持 `node_id` 统一覆盖，无节点候选返回失败原因

## 3. 后端测试

- [x] 3.1 新增列表测试：快审/精审分流、越权项目 404
- [x] 3.2 新增批量确认测试：默认推荐节点、统一节点覆盖、部分失败保持待采纳
- [x] 3.3 新增批量拒绝测试：状态变为已拒绝并从待审列表移除
- [x] 3.4 运行 `cd backend && .venv/bin/pytest -q`
- [x] 3.5 运行 `cd backend && .venv/bin/ruff check .`

## 4. 前端 API 与类型

- [x] 4.1 新增 `ReviewCandidatePayload` 与 `ProjectBatchDecisionPayload/Result` 类型
- [x] 4.2 新增 `fetchReviewCandidates` 与 `batchDecideProjectCandidates` 客户端函数
- [x] 4.3 在 `queryKeys` 增加 `reviewCandidates`

## 5. 前端批量视图

- [x] 5.1 `ReviewPage` 增加「按采集审阅 / 批量处理」切换
- [x] 5.2 新增 `BatchReviewView`：按推荐目录分组、展开来源证据
- [x] 5.3 工具栏：批量确认并归档、批量拒绝、修改目录（统一节点覆盖）
- [x] 5.4 「已分流精审」区勾选禁用，「精审」按钮切回按采集审阅并定位 Source
- [x] 5.5 使用 `useGroveMutation` 并显式失效候选/来源/目录树查询

## 6. 前端测试与构建

- [x] 6.1 新增 `ReviewPage`/`BatchReviewView` 测试：切换、分组、批量确认调用、精审跳转
- [x] 6.2 运行 `cd frontend && npm run test:run`
- [x] 6.3 运行 `cd frontend && npm run lint`
- [x] 6.4 运行 `cd frontend && npm run build`

## 7. 收尾

- [x] 7.1 再次运行 `openspec validate --all --strict`
- [x] 7.2 运行 `openspec archive add-batch-candidate-review`
- [x] 7.3 本地中文 Conventional Commit，不 push、不 merge，等待用户确认
