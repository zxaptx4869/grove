## 1. 后端

- [ ] 1.1 `api/sources.py`：`update_source` 移除 done 锁、加 processing 锁；`delete_source` 改为任一证据即 409、移除 done 锁、加 processing 锁
- [ ] 1.2 `api/sources.py`：`_source_state_counts` 增加待确认候选计数；`schemas/source.py` `SourceOut` 增加 `pending_candidate_count`

## 2. 后端测试

- [ ] 2.1 `test_source_guards.py`：done 未确认可改/可删；processing 改/删 409；证据来源改/删 409

## 3. 前端

- [ ] 3.1 `SourceList`：文案「提取完成」；副徽标（待确认 N/部分确认/N 条正式知识/已处理）；操作可见性（非锁定且非 processing）；删除确认（pending>0）
- [ ] 3.2 前端测试：副徽标、操作可见性、删除确认

## 4. 全量验证与收尾

- [ ] 4.1 后端 `pytest` + `ruff`、前端 `test:run` + `build` + lint 通过
- [ ] 4.2 `openspec validate --all --strict` 通过后归档并同步主规格
- [ ] 4.3 本地提交（不 push、不 merge）
