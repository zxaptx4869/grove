## 1. 规划工件

- [x] 1.1 `proposal.md`、`design.md`、`tasks.md`、`specs/` 四类工件齐备，`openspec validate --all --strict` 通过。

## 2. 后端采集合同

- [ ] 2.1 `Source` 增加 `capture_key`（String(128)、可空）与 `(workspace_id, capture_key)` 唯一索引；新增 Alembic 迁移，`alembic upgrade head` 在含既有数据的库上成功，`downgrade` 可回滚。
- [ ] 2.2 `POST /api/sources` 支持可选 `capture_key`：命中返回 200 与已存在 Source、不落盘；未命中 201；超长 400；未带键行为不变；并发同键由唯一索引兜底并清理本次已落盘文件。验收：同键两次提交只产生一条来源、不同键产生两条、跨 Workspace 同键不命中。
- [ ] 2.3 `POST /api/sources` 支持可选 `title`：传入生效（strip + 截断 255），未传/仅空白保持默认。验收：两条路径各有用例。
- [ ] 2.4 `SourceOut` 增加 `failure_reason` 与 `retry_count`，口径为「仅 failed 且有 error 时给出文案」；所有返回路径一致，任务信息批量读取不产生 N+1。验收：`failed` 与正常状态取值用例 + 查询计数断言。

## 3. Web 端接入

- [ ] 3.1 `SourceCapture` 提交携带 `capture_key`，失败重试复用、成功与草稿变化后重置；`npm run typecheck` / `npm run test:run` / `npm run lint` 通过。

## 4. 验证与收尾

- [ ] 4.1 `cd backend && .venv/bin/pytest tests/test_sources.py tests/test_source_guards.py tests/test_processing.py` 全部通过；`.venv/bin/ruff check` 通过。
- [ ] 4.2 本地起后端 `curl` 冒烟：未认证 `POST /api/sources` 返回 401（非 404），认证后提交返回 201/200。
- [ ] 4.3 每段可验证修改做本地提交（中文 Conventional Commits），输出改动清单、规格条目、验证命令与结果、未验证项与人工走查清单；**不推送、不合并、不归档**，停下等人工验收。
