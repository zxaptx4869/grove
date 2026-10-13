## Context

Web 项目页的「AI 阅读」由旧 Reader 链路承载：前端 `frontend/src/components/features/ReaderView.tsx` 调用 `frontend/src/lib/api.ts` 的 `askReader` / `saveReaderAnswer`，后端 `backend/app/api/reader.py` 暴露 `/api/projects/{id}/reader/ask` 与 `/save-candidate`，服务与 Agent 在 `backend/app/services/reader.py`、`backend/app/agents/reader.py`、`backend/app/schemas/reader.py`。该链路在 `backend/app/api/reader.py:3` 与 `backend/app/services/reader.py:3` 已被标注为「知识 Agent 上线后保留的兼容边界，迁移与人工验收后再单独移除」，`openspec/changes/archive/2026-08-30-add-native-knowledge-agent-conversation/proposal.md` 也把 Web 旧入口列为单独规划项。

约束：知识 Agent 与旧 Reader 共用三个底座模块（`app/agents/semantic.py`、`app/services/vector_search.py`、`app/services/candidate_creation.py`），必须在删除时保留；`answer-to-candidate` 主规格目前混有旧 Reader 保存契约与知识 Agent 共享契约；产品蓝图 `docs/产品蓝图/目录与知识空间.md` 把「现有项目页入口可在统一对话入口接入前作为过渡保留」。

## Goals / Non-Goals

**Goals:**

- 从 Web 与后端彻底移除旧 Reader 链路，收敛到统一「知识 Agent」入口。
- 保持知识 Agent、移动端与共享底座行为不变。
- 让主规格与实现一致：不再要求项目内导航提供「AI 阅读」。

**Non-Goals:**

- 不改知识 Agent 运行时、AI 编排、预算与降级口径。
- 不做数据迁移或历史数据清理；不做统一对话入口改造。

## Decisions

1. **整体移除而非保留后端兼容端点。** 旧 Reader 端点唯一调用方是 `backend/tests/test_reader.py`，Web 与移动端同仓同发布、无跨版本客户端兼容压力。备选「只删 UI、留端点」被否：会留下无人调用且与知识 Agent 契约分叉的死代码与陈旧规格。
2. **必须保留的共享底座清单（不删、不改语义）**：`app/agents/semantic.py`、`app/services/vector_search.py`、`app/services/candidate_creation.py`。证据：知识 Agent 通过 `backend/app/services/knowledge_agent/candidate.py:71`、`:1170` 调用 `create_candidate_from_answer`；通过 `knowledge_agent/tools.py` 使用 `hybrid_recall_by_query_with_meta` 与 `run_semantic_agent`。
3. **`SOURCE_KIND_READER` 常量与 `_SOURCE_TITLE_PREFIX` 的 reader 映射保留。** `create_candidate_from_answer` 的默认参数为 `source_kind: str = SOURCE_KIND_READER`（`backend/app/services/candidate_creation.py:66`），且 `_SOURCE_TITLE_PREFIX.get(source_kind, SOURCE_KIND_READER)`（`:76`）以它兜底；删除会破坏默认值/兜底并影响历史 Source 标题口径。
4. **旧深链接 `/projects/:id?view=ai-read` 重定向到项目首页（`replace`）。** `/agent` 不接收项目/范围 URL 参数（`frontend/src/pages/KnowledgeAgentPage.tsx` 无 `useSearchParams`），跳过去会丢项目上下文；`AppShell` 的 `switchProject`（`frontend/src/components/layout/AppShell.tsx:149`）原样保留 `location.search`，不清理会把死参数带到其他项目。备选「跳 `/agent`」被否（丢上下文）；备选「不处理」被否（URL 残留死参数）。
5. **`EntryPreviewDialog` 一并删除。** 全库仅被 `ReaderView` 引用；Web 知识 Agent 用自带的内联引用块（`frontend/src/pages/KnowledgeAgentPage.tsx:210`、`:228`），无其他消费者。
6. **`answer-to-candidate` 规格收敛。** 旧 Reader 保存契约（保存前可编辑 / 创建虚拟 Source / 回答转 Candidate / 目录推荐 / 引用校验）随入口移除；「旧 Reader 与 Knowledge Agent 复用 Candidate 创建服务」改名并保留为「Knowledge Agent 复用 Candidate 创建服务」。备选「保留全部旧需求」被否：会留下无实现的绑定需求，尤其「引用校验」是旧 Reader 的客户端引用契约，与知识 Agent 的 Run-backed Evidence 契约方向相反。
7. **不做数据迁移。** 旧 Reader 产生的虚拟 Source / Candidate 已落既有表；删端点不影响历史数据，`SOURCE_KIND_READER` 标题映射保留使其仍可读。

## Risks / Trade-offs

- [删除共享模块或 `SOURCE_KIND_READER` 导致知识 Agent 保存或召回异常] → 决策 2、3 明确保留清单；后端全量 `pytest` 覆盖 Agent 用例回归。
- [Web 残留 `reader` 引用导致构建或类型失败] → `npm run typecheck && npm run lint && npm run test:run`，并全库检索 `Reader` / `ai-read` / `readerPreview`。
- [旧书签落点与预期不符] → 走查清单确认重定向行为，由用户判定。
- [规格收敛过度或不足] → 归档前逐条比对 `product-shell` 与 `answer-to-candidate` 主规格，并同步 `answer-to-candidate` 的 Purpose 措辞。

## Migration Plan

1. 纯删除改动，无 Alembic 迁移、无数据回填。
2. 后端重启后旧 Reader 两个端点应返回 404（路由已移除），`/api/knowledge-agent/*` 保持原有 401/200。
3. 回滚策略：还原本次提交即可；无数据变更，回滚无副作用。

## Open Questions

无。深链接重定向方式、孤儿组件处理与原型目录去留均已确认；Web 走查结论由用户给出。
