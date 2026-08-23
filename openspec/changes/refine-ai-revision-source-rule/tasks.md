## 1. 后端

- [ ] 1.1 `schemas/entry.py`：`ApplyRevisionSuggestionRequest` 增加 `external_supplemented: bool = False`
- [ ] 1.2 `services/entry.py`：`apply_ai_revision_to_entry` 仅在 `changed and payload.external_supplemented` 时创建虚拟 Source

## 2. 后端测试

- [ ] 2.1 更新 `test_apply_revision_suggestion_updates_entry_and_version`（external=true 建来源）；新增 external=false 纯格式调整只记版本不建来源的用例

## 3. 前端

- [ ] 3.1 `lib/api.ts`：`ApplyRevisionSuggestionPayload` 增加 `external_supplemented`
- [ ] 3.2 `RevisionSuggestionDialog.tsx`：应用时回传 `draft.external_supplemented`
- [ ] 3.3 `EntryActionsDialogs.test.tsx`：断言应用请求携带 `external_supplemented=true`

## 4. 全量验证与收尾

- [ ] 4.1 后端 `pytest` + `ruff`、前端 `test:run` + `build` + lint 通过
- [ ] 4.2 `openspec validate --all --strict` 通过后归档并同步主规格
- [ ] 4.3 本地提交（不 push、不 merge）
