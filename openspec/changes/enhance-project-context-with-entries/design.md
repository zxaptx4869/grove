## Context

当前 `ProjectContext` 是单行快照，只由项目说明、目录节点和用户纠正生成，不含已确认 Entry；`directory_topics` 是顶级节点名的确定性列表，既用于前端徽章也作为 Agent 的稳定主题摘要。刷新目前只有 1 秒防抖（demo 配置），任何变化都会很快触发重新生成，缺少“重要变化”与频率控制。目录路由与关系判断目前都不消费快照，关系判断使用项目内确定性检索。

## Goals / Non-Goals

**Goals:**

- 把已确认 Entry 的知识覆盖与近期主题纳入快照，生成输入使用实时数据且不自我引用。
- 记录版本号与最近一次更新原因。
- 定义“重要变化白名单 + 防抖 + 最小生成间隔”的触发策略，避免一点改动就重新生成。
- 通过公共上下文接口暴露增强快照，并更新前端展示。

**Non-Goals:**

- 完整版本历史表、语义检索/embedding、Knowledge Gap、Entry 全量入快照、重写路由/关系 Agent 调用链、真实 LLM Provider 接入、Entry 模型变更、跨项目/跨 Workspace 上下文。

## Decisions

### D1：生成输入与输出契约扩展

`ProjectContextGenerator.generate` 输入增加“已确认 Entry 摘要”与“顶级目录节点信息”；输出草稿保持现有三字段并新增 `recent_themes`：

```text
输入（实时组装，不经旧快照）
├── project（说明、生命周期）
├── top_level_nodes：名称 + 截断说明（≤200 字）+ 直接/子树 Entry 数，上限 50 个并附剩余计数
├── entries_summary：确定性聚合（总数、类型分布、节点覆盖、最近 20 条）
└── corrections（用户纠正，跨次保留）
        ↓
输出 ProjectContextDraft
├── project_summary
├── current_focus
├── directory_topics（确定性：顶级节点名，生成器原样保留）
└── recent_themes（AI 提炼 3–5 个）
```

理由：AI 只负责语义提炼，事实性聚合由服务层计算；顶级节点带说明能提高信息确定性，封顶保证 token 有界。

### D2：entries_summary 确定性聚合

在 `services/project_context.py` 中新增聚合函数，从 Entry 表计算：

```text
{
  "total": int,
  "by_type": {"knowledge": n, "method": n, "parameter": n, "reminder": n},
  "by_top_node": [{"node_id": id, "name": name, "count": n}],
  "recent": [{"entry_id": id, "title": title, "node_name": name, "updated_at": iso}]
}
```

- 近期条目按 `updated_at` 倒序取 20 条；
- 顶级节点按“该节点直接 Entry + 全部后代节点 Entry”计数，不枚举叶子；
- 超过 50 个顶级节点时只保留前 50 个并记录 `truncated_count`。

理由：个人知识库规模下 SQL 聚合即可，不引入新依赖；结构稳定，后续语义检索可替换检索层。

### D3：ProjectContext 存储扩展

`project_contexts` 新增列：

- `version`：`Integer`，默认 0，成功生成 +1；
- `last_update_reason`：`String(32)`，可空；
- `entries_summary`：`Text`，可空，JSON；
- `recent_themes`：`Text`，可空，JSON 数组。

理由：沿用单行快照模型；版本号表达“生成次数”，不做历史表。

### D4：版本与更新原因

- `schedule_refresh(db, project_id, reason=None)`：写入 `last_update_reason` 并设置 `refresh_due_at`；
- `refresh_project_context` 成功时 `version += 1`，失败不递增；
- 手动刷新调用 `refresh_project_context` 并记录 `manual_refresh`。

理由：原因字段由触发点显式传入，防抖合并时取最近一次触发原因，简单可审计。

### D5：触发策略

新增配置 `context_min_interval_seconds`（默认 300），`context_refresh_debounce_seconds` 默认调为 60：

```text
refresh_due_at = max(now + debounce, last_success_generated_at + min_interval)
```

- 重要变化才调用 `schedule_refresh`：`entry_archived`、`entry_edited`（新建/编辑/移动/应用修订）、`directory_changed`、`project_updated`、`user_correction`；
- `add_evidence`、浏览、候选处理不触发；
- 手动刷新绕过两个限制立即生成。

理由：防抖合并突发，最小间隔控制频率下限，避免“每确认一条就生成一次”。

### D6：触发点接入

- `services/entry.py`：`archive_candidate` 触发 `entry_archived`；`edit_entry` 内容/类型/条件/说明/节点变化时触发 `entry_edited`；`apply_revision_to_entry` 触发 `entry_edited`；`add_evidence_to_entry` 不触发。
- `api/projects.py`：目录与项目说明变化补传 `directory_changed` / `project_updated`。
- `api/project_context.py`：纠正传 `user_correction`；手动刷新传 `manual_refresh`。

理由：Entry 是知识内容变化的来源；补来源只影响溯源，不影响知识覆盖与近期主题。

### D7：输出契约与前端展示

`ProjectContextOut` 增加 `version`、`last_update_reason`、`entries_summary`（结构化）与 `recent_themes`。公共上下文接口原样返回。

前端 `ProjectContextPanel`：

- 目录主题徽章改为从项目目录树实时派生（ProjectPage 已加载树）；
- 新增展示近期主题、Entry 覆盖统计、版本与最近更新原因。

理由：快照保持 Agent 稳定摘要语义，前端避免展示过期主题。

### D8：demo 生成器

`DemoProjectContextGenerator` 从传入的 `entries_summary` 生成确定性输出：`recent_themes` 取最近条目标题去重后前 3–5 个，无 Entry 时为空；`directory_topics` 保持顶级节点名。

理由：不接真实 Provider 也能走通全流程并用于测试。

### D9：真实 LLM 生成器接入

新增 `context/llm.py` 的 `LLMProjectContextGenerator`：使用 `get_text_model(workspace_id)` 获取 Workspace 文本模型，通过 PydanticAI 结构化输出生成 `project_summary`、`current_focus`、`recent_themes`；`directory_topics` 由提示词约束为原样返回顶级节点名。模型不可用（TestModel / 无密钥）时回退为与 demo 一致的确定性输出。

工厂默认返回 `llm` 生成器，`CONTEXT_GENERATOR=demo` 可切回确定性实现。生成器接口增加 `db` 参数以读取模型配置。

理由：系统内已配置真实 key；真实模型才能产出有意义的项目概要，demo 只是兜底。离线回退保证测试与无密钥环境仍可运行。

## Risks / Trade-offs

- [快照短暂滞后于实时数据] → 关系判断保留项目内直接检索兜底；前端目录徽章改用实时树。
- [token 成本随节点/Entry 增长] → 顶级节点上限 50、说明截断 200 字、近期条目 20 条封顶，成本有界。
- [version 不能表达内容变化量] → 文档明确版本只代表成功生成次数，变化量由防抖合并决定。
- [archive 与新增节点归档双触发] → 防抖合并为一次刷新，不影响语义。
- [最小间隔导致快照较旧] → 默认 5 分钟，真实使用后按指标校准。

## Migration Plan

一个 Alembic 迁移为 `project_contexts` 增加四个可空列（`version` 带 server_default 0），无回填；旧快照回读时版本按 0 展示，首次成功生成后为 1。回滚即删列。

## Open Questions

- 防抖 60s 与最小间隔 300s 为初始默认，按真实使用数据校准。
- 近期条目 20 条与顶级节点 50 个上限同样按真实数据校准，不改接口结构。
