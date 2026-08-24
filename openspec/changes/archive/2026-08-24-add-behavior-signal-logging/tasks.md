## 1. OpenSpec 工件

- [x] 1.1 创建 change `add-behavior-signal-logging` 并编写 proposal / specs / design / tasks
- [x] 1.2 `openspec validate --all --strict` 通过

## 2. 后端实现

- [x] 2.1 新增 `BehaviorSignal` 模型与 Alembic 迁移（外键置空保留、workspace_id 非空）
- [x] 2.2 新增 `record_behavior_signal` 服务与 `GET /api/behavior-signals` 只读接口（Workspace 隔离、类型/项目过滤、分页）
- [x] 2.3 `sources.update_source` 修改项目归属记录 `project_decision`
- [x] 2.4 `candidate_review`：`edit_candidate` 记录 `content_edit`；批量拒绝与批量改目录逐条记录 `node_decision`
- [x] 2.5 `entry`：`archive_candidate` / `archive_candidate_with_new_node` 记录 `node_decision`；`add_evidence_to_entry` / `apply_revision_to_entry` 记录 `relation_decision`
- [x] 2.6 后端测试：四类信号写入、接受度判定、跨 Workspace 隔离、删除后保留、只读接口过滤与分页

## 3. 验证与收尾

- [x] 3.1 后端 `pytest` + `ruff` 通过
- [x] 3.2 `openspec validate --all --strict` 通过后归档同步主规格
- [x] 3.3 本地提交（不 push、不 merge）
