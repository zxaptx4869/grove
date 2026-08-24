## 1. 后端

- [x] 1.1 `agents/organizing.py`：SYSTEM_PROMPT 规则 7 改为必答；`run_organizing_agent` 增加未归属漏推荐时的重试（保留首次候选，仅补充有效项目推荐）

## 2. 后端测试

- [x] 2.1 断言提示词包含必选项目要求；重试逻辑仅补充项目推荐且不覆盖候选（构造可测的最小单元）

## 3. 全量验证与收尾

- [x] 3.1 后端 `pytest` + `ruff` 通过
- [x] 3.2 `openspec validate --all --strict` 通过后归档并同步主规格
- [x] 3.3 本地提交（不 push、不 merge）
