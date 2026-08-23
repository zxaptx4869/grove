## 1. 后端

- [ ] 1.1 `agents/revision.py`：`RevisionReplyDraft` 增加 `intent: discuss | propose`（默认 discuss）；提示词收敛为一句规则；离线兜底返回 `intent=discuss`
- [ ] 1.2 `schemas/entry.py`：`RevisionSuggestionOut` 增加 `intent` 字段
- [ ] 1.3 `services/entry.py`：新增 `_normalize_revision_reply`（discuss 丢草稿 / propose 缺草稿降级 discuss，均记录告警日志）并接入响应组装

## 2. 后端测试

- [ ] 2.1 `tests/test_entry_version.py` 离线降级断言 `intent=discuss`；新增归一化单测（discuss 带草稿丢弃、propose 缺草稿降级）

## 3. 前端

- [ ] 3.1 `lib/api.ts`：`RevisionSuggestionPayload` 增加 `intent`
- [ ] 3.2 `RevisionSuggestionDialog.tsx`：按 `intent` 决定更新草稿或仅追加回复
- [ ] 3.3 `EntryActionsDialogs.test.tsx`：mock 带 `intent`；讨论轮（discuss）不更新草稿、提出轮（propose）更新草稿

## 4. 全量验证与收尾

- [ ] 4.1 后端 `pytest` + `ruff`、前端 `test:run` + `build` + lint（无本 change 新增问题）通过
- [ ] 4.2 `openspec validate --all --strict` 通过后归档 `add-ai-revision-discussion-intent` 并同步主规格
- [ ] 4.3 更新 `docs/discussions` 相关文档状态；本地提交（不 push、不 merge）
