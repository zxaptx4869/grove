## 1. 后端

- [x] 1.1 `api/sources.py`：`update_source` 增加 done 409；`delete_source` 增加 done 409（保持既有错误优先级）

## 2. 后端测试

- [x] 2.1 `test_source_guards.py`：done 来源改归属 409、删除 409；既有归档/唯一证据用例不受影响

## 3. 前端

- [x] 3.1 `SourceList.tsx`：`status === 'done'` 不渲染改归属与删除
- [x] 3.2 `SourceHistoryPage.tsx`：搜索防抖自动查询 + 清空按钮回到全部
- [x] 3.3 前端测试：done 行无操作；清空后查询回到全部

## 4. 全量验证与收尾

- [x] 4.1 后端 `pytest` + `ruff`、前端 `test:run` + `build` + lint 通过
- [x] 4.2 `openspec validate --all --strict` 通过后归档并同步主规格
- [x] 4.3 本地提交（不 push、不 merge）
