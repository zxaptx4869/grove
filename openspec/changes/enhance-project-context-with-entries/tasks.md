## 1. 骨架与数据模型

- [x] 1.1 新增 Alembic 迁移，为 `project_contexts` 增加 `version`、`last_update_reason`、`entries_summary`、`recent_themes` 可空列
- [x] 1.2 更新 `ProjectContext` 模型与字段注释
- [x] 1.3 更新 `ProjectContextOut`，增加 `version`、`last_update_reason`、结构化 `entries_summary` 与 `recent_themes`

验收：`cd backend && .venv/bin/alembic upgrade head && .venv/bin/ruff check .`

## 2. 聚合与生成器

- [x] 2.1 在 `services/project_context.py` 实现 `entries_summary` 确定性聚合（总数、类型分布、顶级节点覆盖、最近 20 条）
- [x] 2.2 实现顶级节点信息组装：名称 + 截断说明（≤200 字）+ 直接/子树 Entry 数，上限 50 并记录剩余计数
- [x] 2.3 扩展 `ProjectContextDraft` 与 `ProjectContextGenerator` 接口：输入 `entries_summary` 与顶级节点信息，输出 `recent_themes`
- [x] 2.4 更新 demo 生成器：`recent_themes` 从最近条目标题确定性提炼，`directory_topics` 保持顶级节点名
- [x] 2.5 新增 `LLMProjectContextGenerator`（真实文本模型 + 无密钥离线回退），工厂默认接入并支持 `demo` 切换

验收：`cd backend && .venv/bin/pytest -q && .venv/bin/ruff check .`

## 3. 触发策略与接入

- [x] 3.1 新增配置 `context_min_interval_seconds`（默认 300），`context_refresh_debounce_seconds` 默认改为 60
- [x] 3.2 `schedule_refresh` 支持 `reason` 参数，并按 `max(now + debounce, 上次成功生成 + 最小间隔)` 计算刷新时间
- [x] 3.3 `refresh_project_context` 成功时 `version += 1` 并写入新字段，失败不递增
- [x] 3.4 Entry 服务接入触发点：归档 `entry_archived`、编辑/应用修订 `entry_edited`，补充来源证据不触发
- [x] 3.5 项目/目录接口补 `directory_changed` / `project_updated`；纠正与手动刷新记录 `user_correction` / `manual_refresh`

验收：`cd backend && .venv/bin/pytest -q && .venv/bin/ruff check .`

## 4. API 与前端

- [x] 4.1 公共上下文接口返回新增字段
- [x] 4.2 扩展 `lib/api.ts` 的 `ProjectContextPayload` 与相关类型
- [x] 4.3 `ProjectContextPanel` 展示近期主题、Entry 覆盖、版本与更新原因；目录主题徽章改为从目录树派生
- [x] 4.4 补充项目上下文面板的前端测试

验收：`cd frontend && npm run test:run && npm run build`

## 5. 验证与收尾

- [x] 5.1 运行 `openspec validate --all --strict` 确认规格与变更通过校验
- [x] 5.2 运行后端测试与静态检查
- [x] 5.3 运行前端测试与构建
- [ ] 5.4 手动走查项目上下文面板展示与触发更新策略
