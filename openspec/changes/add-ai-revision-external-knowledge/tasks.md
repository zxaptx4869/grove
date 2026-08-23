## 1. 后端

- [ ] 1.1 `agents/revision.py`：提示词允许结合外部知识（回复文字标注 + 草稿 `external_supplemented` 标记，不编造来源证据）；`RevisionDraft` 增加 `external_supplemented`
- [ ] 1.2 `schemas/entry.py`：`RevisionDraftPayload` 增加 `external_supplemented`；`ApplyRevisionSuggestionRequest` 增加 `instruction / ai_reply / reason / provider / model`（可选）
- [ ] 1.3 `services/entry.py`：应用 AI 修订时创建虚拟 Source + Attachment + Extraction + 来源证据（仅实际修改时），并追加版本

## 2. 后端测试

- [ ] 2.1 `tests/test_entry_version.py`：应用草稿后来源证据新增「AI 修订建议」虚拟 Source、Extraction 记录 provider/model、版本与变更说明正确；未应用不落任何数据

## 3. 前端

- [ ] 3.1 `lib/api.ts`：`RevisionDraftPayload` 增加 `external_supplemented`；`ApplyRevisionSuggestionPayload` 增加 AI 元数据字段
- [ ] 3.2 `RevisionSuggestionDialog.tsx`：记录并回传 AI 元数据；`external_supplemented=true` 时草稿区显示「含 AI 外部补充」徽标
- [ ] 3.3 `EntryActionsDialogs.test.tsx`：应用请求包含 AI 元数据；外部补充徽标展示

## 4. 全量验证与收尾

- [ ] 4.1 后端 `pytest` + `ruff`、前端 `test:run` + `build` + lint（无本 change 新增问题）通过
- [ ] 4.2 `openspec validate --all --strict` 通过后归档 `add-ai-revision-external-knowledge` 并同步主规格
- [ ] 4.3 本地提交（不 push、不 merge）
